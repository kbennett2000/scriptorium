"""Library + checkout API (DESIGN §11.1 library group) — the bridge to the reader.

Three read-only, unauthenticated (ADR-0005, LAN trust) endpoints over published ``library/{id}``
bundles:

- ``GET /api/library`` — the shelf listing (id, title, author, cover thumb URL, revision, download
  size). ``total_bytes_reader`` is the **resolved** reader set (current ``-rN`` variants only, via
  :mod:`scriptorium.library.checkout`), i.e. what the reader actually downloads.
- ``GET /api/library/{id}/manifest`` — ``manifest.json`` verbatim (the full additive ledger).
- ``GET /api/library/{id}/files/{file_path}`` — bundle file serving, path-traversal-guarded, with
  ``ETag = sha256`` (from the manifest) and ``If-None-Match`` → 304.

Served **only** from ``cfg.library_dir`` — ``work/`` is never reachable here.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from ..config import Config, load_config
from .checkout import resolved_total_bytes

router = APIRouter(prefix="/api/library")

_CONTENT_TYPES = {".json": "application/json", ".webp": "image/webp", ".png": "image/png"}


def _bundle_dir(cfg: Config, book_id: str) -> Path:
    """Resolve ``library/{book_id}`` inside the library root, or raise 404.

    The ``.resolve()`` + ``is_relative_to`` check keeps a hostile ``book_id`` (``..``) from
    escaping the library root even though FastAPI path params never span ``/``.
    """
    root = cfg.library_dir.resolve()
    bundle = (root / book_id).resolve()
    if not bundle.is_relative_to(root) or not (bundle / "manifest.json").is_file():
        raise HTTPException(status_code=404, detail=f"no such book {book_id!r}")
    return bundle


def _load_manifest(bundle: Path) -> dict[str, Any]:
    return json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))


def _content_type(path: Path) -> str:
    return _CONTENT_TYPES.get(path.suffix, "application/octet-stream")


def _etag_map(manifest: dict[str, Any]) -> dict[str, str]:
    return {f["path"]: f["sha256"] for f in manifest.get("files", [])}


@router.get("")
def list_library() -> list[dict[str, Any]]:
    """List published books for the shelf. Best-effort: skip unreadable/incomplete bundles."""
    cfg = load_config()
    root = cfg.library_dir
    books: list[dict[str, Any]] = []
    if not root.is_dir():
        return books
    for entry in sorted(root.glob("*")):
        if not entry.is_dir() or not (entry / "manifest.json").is_file():
            continue
        try:
            manifest = _load_manifest(entry)
            meta = json.loads((entry / "meta.json").read_text(encoding="utf-8"))
            book_id = manifest["book_id"]
            books.append({
                "id": book_id,
                "title": meta["title"],
                "author": meta["author"],
                "cover_thumb_url": f"/api/library/{book_id}/files/images/thumbs/cover.webp",
                "revision": manifest["revision"],
                "total_bytes_reader": resolved_total_bytes(manifest),
            })
        except Exception:
            # A malformed bundle dir must not break the whole shelf.
            continue
    return books


@router.get("/{book_id}/manifest")
def get_manifest(book_id: str) -> JSONResponse:
    """Serve ``manifest.json`` verbatim — the full additive ledger (all ``-rN`` variants)."""
    cfg = load_config()
    bundle = _bundle_dir(cfg, book_id)
    return JSONResponse(_load_manifest(bundle))


@router.get("/{book_id}/files/{file_path:path}")
def get_file(book_id: str, file_path: str, request: Request) -> Response:
    """Serve a bundle file with a sha256 ETag; ``If-None-Match`` short-circuits to 304."""
    cfg = load_config()
    bundle = _bundle_dir(cfg, book_id)

    target = (bundle / file_path).resolve()
    if not target.is_relative_to(bundle):
        raise HTTPException(status_code=400, detail="bad path")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="no such file")

    rel = target.relative_to(bundle).as_posix()
    sha = _etag_map(_load_manifest(bundle)).get(rel)
    if sha is None:  # not tracked in the manifest (e.g. manifest.json itself) — hash on the fly
        sha = hashlib.sha256(target.read_bytes()).hexdigest()
    etag = f'"{sha}"'

    if_none_match = request.headers.get("if-none-match", "")
    tokens = {t.strip() for t in if_none_match.split(",")}
    if etag in tokens or "*" in tokens:
        return Response(status_code=304, headers={"ETag": etag})

    return FileResponse(target, media_type=_content_type(target), headers={"ETag": etag})
