"""Picture-sets API (DESIGN §8, ADR-0014).

Per-user picture "sets" for a book: list, create (in a chosen style or a re-roll), and delete. Every
book has a synthetic ``default`` set — its shipped bundle art — which every profile starts on. The
render itself runs on the single-worker runner (:mod:`scriptorium.artsets.phase`); the create call
is the review-gate approval. No auth (ADR-0005, LAN trust); ``{user}``/``{book}``/``{set_id}`` are
pattern-validated so no path segment can traverse out, exactly as in the sync API. The composite
set-job id (``{book}#{set_id}``) is kept server-internal — ``#`` is a URL-fragment delimiter.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from ..config import Config, load_config
from . import service

router = APIRouter(prefix="/api")

# {user}/{book}/{set_id} shapes (mirror sync/api.py) — the first traversal guard.
_USER_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_BOOK_RE = re.compile(r"^(pg-[0-9]+|usr-[0-9a-f]{12})$")
_SET_RE = re.compile(r"^set-[0-9a-f]{12}$")

# Set images are the same asset kinds a book bundle serves (mirror library/api.py).
_CONTENT_TYPES = {".json": "application/json", ".webp": "image/webp", ".png": "image/png"}


class CreateSetBody(BaseModel):
    kind: str = "style"
    style_id: str | None = None
    label: str | None = None


def _require_path(user: str, book: str) -> None:
    """Reject malformed ``{user}``/``{book}`` segments (400) — the traversal guard."""
    if not _USER_RE.match(user):
        raise HTTPException(status_code=400, detail=f"bad user id {user!r}")
    if not _BOOK_RE.match(book):
        raise HTTPException(status_code=400, detail=f"bad book id {book!r}")


@router.get("/artsets/{user}/{book}")
def list_sets(user: str, book: str) -> dict[str, Any]:
    """List a user's picture sets for a book (the synthetic default plus any personal sets)."""
    _require_path(user, book)
    return service.list_sets(load_config(), user, book)


@router.post("/artsets/{user}/{book}")
def create_set(user: str, book: str, body: CreateSetBody) -> dict[str, Any]:
    """Create a personal set + enqueue its render (the create action is the approval, ADR-0014)."""
    _require_path(user, book)
    try:
        return service.create_set(load_config(), user, book, body.kind, body.style_id, body.label)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/artsets/{user}/{book}/{set_id}")
def delete_set(user: str, book: str, set_id: str) -> dict[str, Any]:
    """Delete a personal set (its subtree + job). Refuses the synthetic default."""
    _require_path(user, book)
    if not _SET_RE.match(set_id):
        raise HTTPException(status_code=400, detail=f"bad set id {set_id!r}")
    service.delete_set(load_config(), user, book, set_id)
    return {"deleted": set_id}


# --- serving (Phase 3): private offline download, mirroring library/api.py ---
#
# The synthetic ``default`` set has no bytes of its own — the reader resolves it from the resident
# book bundle (``/api/library/...``), so it never reaches here (``_SET_RE`` excludes it).


def _set_dir(cfg: Config, user: str, book: str, set_id: str) -> Path:
    """Resolve ``artsets/{user}/{book}/{set_id}`` inside the artsets root, or raise.

    Segments are pattern-validated first (400), then a ``.resolve()`` + ``is_relative_to`` check
    keeps a hostile segment from escaping the root (mirrors ``library.api._bundle_dir``).
    """
    _require_path(user, book)
    if not _SET_RE.match(set_id):
        raise HTTPException(status_code=400, detail=f"bad set id {set_id!r}")
    root = cfg.artsets_dir.resolve()
    set_dir = (root / user / book / set_id).resolve()
    if not set_dir.is_relative_to(root) or not (set_dir / "manifest.json").is_file():
        raise HTTPException(status_code=404, detail=f"no such set {set_id!r}")
    return set_dir


def _load_manifest(set_dir: Path) -> dict[str, Any]:
    return json.loads((set_dir / "manifest.json").read_text(encoding="utf-8"))


def _content_type(path: Path) -> str:
    return _CONTENT_TYPES.get(path.suffix, "application/octet-stream")


def _etag_map(manifest: dict[str, Any]) -> dict[str, str]:
    return {f["path"]: f["sha256"] for f in manifest.get("files", [])}


@router.get("/artsets/{user}/{book}/{set_id}/manifest")
def get_set_manifest(user: str, book: str, set_id: str) -> JSONResponse:
    """Serve a personal set's ``manifest.json`` verbatim (same shape as a book manifest)."""
    set_dir = _set_dir(load_config(), user, book, set_id)
    return JSONResponse(_load_manifest(set_dir))


@router.get("/artsets/{user}/{book}/{set_id}/files/{file_path:path}")
def get_set_file(
    user: str, book: str, set_id: str, file_path: str, request: Request
) -> Response:
    """Serve a set image with a sha256 ETag; ``If-None-Match`` short-circuits to 304."""
    set_dir = _set_dir(load_config(), user, book, set_id)

    target = (set_dir / file_path).resolve()
    if not target.is_relative_to(set_dir):
        raise HTTPException(status_code=400, detail="bad path")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="no such file")

    rel = target.relative_to(set_dir).as_posix()
    sha = _etag_map(_load_manifest(set_dir)).get(rel)
    if sha is None:  # not tracked in the manifest (e.g. manifest.json itself) — hash on the fly
        sha = hashlib.sha256(target.read_bytes()).hexdigest()
    etag = f'"{sha}"'

    if_none_match = request.headers.get("if-none-match", "")
    tokens = {t.strip() for t in if_none_match.split(",")}
    if etag in tokens or "*" in tokens:
        return Response(status_code=304, headers={"ETag": etag})

    return FileResponse(target, media_type=_content_type(target), headers={"ETag": etag})
