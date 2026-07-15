"""Picture-sets API (DESIGN §8, ADR-0014).

Per-user picture "sets" for a book: list, create (in a chosen style or a re-roll), and delete. Every
book has a synthetic ``default`` set — its shipped bundle art — which every profile starts on. The
render itself runs on the single-worker runner (:mod:`scriptorium.artsets.phase`); the create call
is the review-gate approval. No auth (ADR-0005, LAN trust); ``{user}``/``{book}``/``{set_id}`` are
pattern-validated so no path segment can traverse out, exactly as in the sync API. The composite
set-job id (``{book}#{set_id}``) is kept server-internal — ``#`` is a URL-fragment delimiter.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import load_config
from . import service

router = APIRouter(prefix="/api")

# {user}/{book}/{set_id} shapes (mirror sync/api.py) — the first traversal guard.
_USER_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_BOOK_RE = re.compile(r"^(pg-[0-9]+|usr-[0-9a-f]{12})$")
_SET_RE = re.compile(r"^set-[0-9a-f]{12}$")


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
