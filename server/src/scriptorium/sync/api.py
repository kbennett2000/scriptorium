"""Sync API (DESIGN §12) — the mutable layer the reader syncs back.

Server-authoritative merge: a client PUTs its full annotations/positions document, the server merges
it into the stored copy (:mod:`scriptorium.sync.merge`), persists atomically, and returns the merged
document. Three concerns wrap the pure merge here:

- **Schema validation both ways** — the incoming body and the merged result are both validated
  against ``shared/schemas`` (a merge must never produce an invalid document).
- **Per-``(user, book)`` serialization** — an ``asyncio.Lock`` per key guards the whole
  read-merge-write cycle so two interleaved PUTs can't lose an update.
- **Versioned backups** — after an annotations merge, a timestamped snapshot is written and the
  history pruned to the newest 20 (DESIGN §12). Positions get no backup by design.

No auth (ADR-0005, LAN trust). ``GET /api/sync/positions`` is deliberately household-visible.
Served entirely under ``cfg.sync_dir``; ``{user}``/``{book}`` are pattern-validated so no path
segment can traverse out.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import jsonschema
from fastapi import APIRouter, HTTPException, Request

from .. import schemas
from ..config import Config, load_config
from ..users.loader import load_users
from .merge import merge_annotations, merge_positions

router = APIRouter(prefix="/api")

# {user}/{book} shapes, taken from the users / annotations schemas. Matching these is the first
# traversal guard: neither pattern admits '/' or '.', so '..' or nested paths can never match.
_USER_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_BOOK_RE = re.compile(r"^(pg-[0-9]+|usr-[0-9a-f]{12})$")

_BACKUP_KEEP = 20

# One lock per (user, book). setdefault is atomic on the single event loop (no await between the
# lookup and the insert), so concurrent PUTs for the same key share one lock and serialize.
_locks: dict[tuple[str, str], asyncio.Lock] = {}


def _lock_for(user: str, book: str) -> asyncio.Lock:
    return _locks.setdefault((user, book), asyncio.Lock())


def _require_path(user: str, book: str) -> None:
    """Reject malformed ``{user}``/``{book}`` segments (400) — the traversal guard."""
    if not _USER_RE.match(user):
        raise HTTPException(status_code=400, detail=f"bad user id {user!r}")
    if not _BOOK_RE.match(book):
        raise HTTPException(status_code=400, detail=f"bad book id {book!r}")


def _doc_path(cfg: Config, kind: str, user: str, book: str) -> Path:
    """Resolve ``sync/{kind}/{user}/{book}.json``, asserting it stays inside ``sync_dir``.

    ``kind`` is ``"annotations"`` or ``"positions"``. The pattern checks in :func:`_require_path`
    already exclude traversal; this ``is_relative_to`` assertion is defense in depth.
    """
    root = cfg.sync_dir.resolve()
    path = (root / kind / user / f"{book}.json").resolve()
    if not path.is_relative_to(root):
        raise HTTPException(status_code=400, detail="bad path")
    return path


def _read_doc(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write(path: Path, doc: dict[str, Any]) -> None:
    """Write ``doc`` as pretty JSON via tmp-file + ``os.replace`` (the ``bake/job.py`` idiom).

    The atomic replace means a crash mid-write can never leave a half-written, unparseable sync doc.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _write_backup_and_prune(cfg: Config, user: str, book: str, doc: dict[str, Any]) -> None:
    """Snapshot the merged annotations doc, then keep only the newest ``_BACKUP_KEEP`` (DESIGN §12).

    Backup filenames are the zero-padded nanosecond clock, so lexical order == chronological order;
    on the (astronomically unlikely) same-ns collision we bump by 1, preserving both uniqueness and
    ordering. Pruning then sorts the directory and unlinks all but the newest 20.
    """
    backup_dir = (cfg.sync_dir / "annotations-backups" / user / book).resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)

    ns = time.time_ns()
    dest = backup_dir / f"{ns:020d}.json"
    while dest.exists():
        ns += 1
        dest = backup_dir / f"{ns:020d}.json"
    dest.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    backups = sorted(backup_dir.glob("*.json"))
    for stale in backups[:-_BACKUP_KEEP]:
        stale.unlink()


def _validate_in(kind: str, body: Any) -> None:
    """Validate a request body against ``kind``'s schema, turning failure into a 422."""
    try:
        schemas.validate(kind, body)
    except jsonschema.ValidationError as exc:
        detail = f"invalid {kind} document: {exc.message}"
        raise HTTPException(status_code=422, detail=detail) from exc


@router.get("/users")
def get_users() -> list[dict[str, Any]]:
    """Household profiles for the reader's profile picker (DESIGN §14)."""
    cfg = load_config()
    return load_users(cfg)


@router.get("/sync/annotations/{user}/{book}")
def get_annotations(user: str, book: str) -> dict[str, Any]:
    """Return the stored annotations doc, or an empty one if ``(user, book)`` has never synced."""
    _require_path(user, book)
    cfg = load_config()
    stored = _read_doc(_doc_path(cfg, "annotations", user, book))
    if stored is None:
        return {"book_id": book, "user_id": user, "annotations": []}
    return stored


@router.put("/sync/annotations/{user}/{book}")
async def put_annotations(user: str, book: str, request: Request) -> dict[str, Any]:
    """Merge the client's annotations doc into the stored copy; back up and return the result."""
    _require_path(user, book)
    body = await request.json()
    _validate_in("annotations", body)
    if body.get("user_id") != user or body.get("book_id") != book:
        raise HTTPException(status_code=400, detail="body identity does not match path")

    cfg = load_config()
    path = _doc_path(cfg, "annotations", user, book)
    async with _lock_for(user, book):
        stored = _read_doc(path) or {"book_id": book, "user_id": user, "annotations": []}
        merged = merge_annotations(stored, body)
        merged["book_id"], merged["user_id"] = book, user  # path is authoritative
        schemas.validate("annotations", merged)
        _atomic_write(path, merged)
        _write_backup_and_prune(cfg, user, book, merged)
    return merged


@router.get("/sync/positions/{user}/{book}")
def get_positions(user: str, book: str) -> dict[str, Any]:
    """Return the stored positions doc, or 404 if this ``(user, book)`` has never synced.

    Household-visible: not restricted by the requesting profile (DESIGN §12; ``PROGRESS_PRIVATE``
    reserved, unimplemented). There is no natural empty position (``page_seq`` is >= 1), so absence
    is a 404 rather than a synthesized default.
    """
    _require_path(user, book)
    cfg = load_config()
    stored = _read_doc(_doc_path(cfg, "positions", user, book))
    if stored is None:
        raise HTTPException(status_code=404, detail="no position yet")
    return stored


@router.put("/sync/positions/{user}/{book}")
async def put_positions(user: str, book: str, request: Request) -> dict[str, Any]:
    """Merge the client's positions doc (furthest-wins + current LWW) and return the result."""
    _require_path(user, book)
    body = await request.json()
    _validate_in("positions", body)

    cfg = load_config()
    path = _doc_path(cfg, "positions", user, book)
    async with _lock_for(user, book):
        stored = _read_doc(path)
        merged = merge_positions(stored, body) if stored is not None else body
        schemas.validate("positions", merged)
        _atomic_write(path, merged)
    return merged
