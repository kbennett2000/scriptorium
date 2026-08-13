"""Picture-set service (DESIGN §8, ADR-0014): create / delete / list a user's sets.

A *set* re-illustrates an already-published book in a chosen style (or a re-roll). Creating one
writes ``set.json`` (``status="generating"``) under ``artsets/{user}/{book}/{set_id}/`` and enqueues
a set-scoped runner job (id ``{book}#{set_id}`` — kept server-internal; ``#`` is a URL delimiter).
user's explicit create action is the review-gate approval (ADR-0014) — there is no separate approve
step, and nothing new is authored (page prompts are the book's approved prompts; cover/portrait are
deterministic template assembly over the approved cast + the fixed style catalog).

Sets never touch ``library/{book}``, so delete is a plain subtree removal — safe by construction.
"""

from __future__ import annotations

import json
import re
import secrets
import shutil
from datetime import UTC, datetime
from typing import Any

from .. import schemas
from ..bake import job as jobmod
from ..bake.job import Job, JobState
from ..config import Config
from ..styles import CUSTOM_STYLE_ID, get_style, load_styles
from .phase import set_render_progress

_SET_ID_RE = re.compile(r"^set-[0-9a-f]{12}$")
_KINDS = ("style", "reroll")


def set_job_id(book: str, set_id: str) -> str:
    """The set-scoped runner job id. Server-internal only (``#`` is a URL-fragment delimiter)."""
    return f"{book}#{set_id}"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _read_json(path: Any) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Any, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _style_ids() -> set[str]:
    return {s["id"] for s in load_styles()["styles"]}


def create_set(
    cfg: Config, user: str, book: str, kind: str, style_id: str | None, label: str | None,
    model: str | None = None, custom_style: str | None = None,
) -> dict:
    """Create a set + enqueue its render job. Returns the ``set.json`` doc (status generating).

    Raises ``LookupError`` if the book is not published, ``ValueError`` on a bad kind/style.
    """
    meta_path = cfg.library_dir / book / "meta.json"
    if not meta_path.is_file():
        raise LookupError(f"book {book!r} is not published")
    meta = _read_json(meta_path)

    if kind not in _KINDS:
        raise ValueError(f"kind must be one of {_KINDS}, not {kind!r}")
    # A re-roll defaults to the book's own published style (incl. its custom free-text look); a
    # style set must name a catalog id or the ``custom`` sentinel (ADR-0031).
    if kind == "reroll" and not style_id:
        style_id = meta.get("style_id")
        if custom_style is None:
            custom_style = meta.get("custom_style")
    if not style_id or (style_id != CUSTOM_STYLE_ID and style_id not in _style_ids()):
        raise ValueError(f"unknown style_id {style_id!r}")
    # Base model (ADR-0030). A re-roll with no explicit model reproduces the book's own model,
    # pinned at publish in ``meta.bake.models.imagegen``; "unknown" (imagegen offline at publish)
    # falls back to the service default. A style set uses the caller's choice (None → default).
    if kind == "reroll" and not model:
        pinned = ((meta.get("bake") or {}).get("models") or {}).get("imagegen")
        model = pinned if pinned and pinned != "unknown" else None

    set_id = "set-" + secrets.token_hex(6)
    if style_id == CUSTOM_STYLE_ID:
        style_name = (custom_style or "").strip() or "Custom"
    else:
        style_name = get_style(style_id)["name"]
    label = label or (style_name if kind == "style" else f"{style_name} (re-roll)")
    source_revision = int(meta.get("revision", 1))

    set_doc = {
        "book_id": book,
        "user_id": user,
        "set_id": set_id,
        "kind": kind,
        "label": label,
        "style_id": style_id,
        "custom_style": custom_style,
        "model": model,
        "source_revision": source_revision,
        "status": "generating",
        "created": _now_iso(),
    }
    schemas.validate("artset", set_doc)
    _write_json(cfg.artsets_dir / user / book / set_id / "set.json", set_doc)

    Job(
        id=set_job_id(book, set_id),
        book_id=book,
        state=JobState.SET_RENDERING,
        source={"user": user, "set_id": set_id, "kind": kind},
        bake_config={
            "style_id": style_id, "custom_style": custom_style, "model": model,
            "source_revision": source_revision,
        },
        started=True,
    ).save(cfg)
    return set_doc


def delete_set(cfg: Config, user: str, book: str, set_id: str) -> None:
    """Remove a set: its job record + its subtree. Refuses the synthetic ``default``.

    Nothing under ``library/{book}`` is touched, so this cannot affect the book or other users.
    """
    if set_id == "default":
        raise ValueError("cannot delete the default set")
    job_file = jobmod.job_path(cfg, set_job_id(book, set_id))
    if job_file.is_file():
        job_file.unlink()
    set_dir = cfg.artsets_dir / user / book / set_id
    if set_dir.is_dir():
        shutil.rmtree(set_dir)


def _summary(cfg: Config, book: str, doc: dict) -> dict:
    """A set-list summary from a set.json doc, reconciling a stalled 'generating' vs its job."""
    status = doc["status"]
    progress: dict | None = None
    if status == "generating":
        job = jobmod.load(cfg, set_job_id(book, doc["set_id"]))
        if job is None or job.state == JobState.FAILED:
            status = "failed"
        elif job.state == JobState.SET_RENDERING:
            # A live count so the reader shows "… X of Y" moving, not frozen text. Best-effort:
            # any read failure (e.g. the book's selection went missing) just omits it.
            try:
                done, total = set_render_progress(cfg, job)
                progress = {"done": done, "total": total}
            except (OSError, KeyError, ValueError):
                progress = None
    summary = {
        "set_id": doc["set_id"], "kind": doc["kind"], "label": doc["label"], "status": status,
    }
    for key in ("style_id", "source_revision", "created"):
        if key in doc:
            summary[key] = doc[key]
    if progress is not None:
        summary["render_progress"] = progress
    return summary


def list_sets(cfg: Config, user: str, book: str) -> dict:
    """List a user's sets for a book: the synthetic ``default`` plus every set.json on disk."""
    sets: list[dict] = [
        {"set_id": "default", "kind": "default", "label": "Default", "status": "ready"}
    ]
    book_root = cfg.artsets_dir / user / book
    if book_root.is_dir():
        for set_dir in sorted(book_root.iterdir()):
            set_json = set_dir / "set.json"
            if set_json.is_file():
                sets.append(_summary(cfg, book, _read_json(set_json)))
    doc = {"book_id": book, "user_id": user, "active_set_id": "default", "sets": sets}
    schemas.validate("artset-list", doc)
    return doc
