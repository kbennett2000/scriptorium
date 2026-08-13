"""Post-publish per-plate picture edits — private per household profile (extends ADR-0014).

A reader can replace one published plate's image with an img2img re-render and give it a new caption
WITHOUT touching the shared, immutable bundle. The replacement image + caption live in a private
overlay at ``artsets/{user}/{book}/edits/`` (outside ``library/``). The reader layers this overlay
over the book (and any active style set), so only that profile sees the change; ``library/{book}``
and the frozen ``pages/*.json`` are never written.

Flow (all synchronous; GPU work goes through the :class:`ImagegenClient`, so a ``GpuUnavailable``
surfaces to the caller and the endpoint maps it to HTTP 503 — never a fallback):

- :func:`plate_context` — the prompt / seed / size + current caption to pre-fill the editor.
- :func:`generate_candidate` — an img2img render (current image = starting image) written to a
  scratch candidate PNG (+ a sidecar recording the params it was made with). Not yet visible.
- :func:`commit_edit` — promote the chosen candidate into the overlay (archival PNG + web/thumb
  derivatives), record the edit + caption in ``edits.json``, and (re)build the overlay
  ``manifest.json`` so the reader can check it out offline exactly like a picture set.

The overlay reuses the picture-set delivery path: it is served as the reserved set id ``"edits"`` by
``artsets/api.py`` (``/manifest`` + ``/files/``) and downloaded by the reader's ``artsetCheckout``.
Its own metadata lives in ``edits.json`` (not a ``set.json``), so it never appears in the reader's
Pictures menu.
"""

from __future__ import annotations

import json
import secrets
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import schemas
from ..bake.phases.p7_render import _asset_spec
from ..bake.phases.p8_publish import build_manifest
from ..config import Config
from ..render.derivatives import make_derivatives
from ..render.imagegen import ImagegenClient

#: The reserved set id the overlay is served under (see artsets/api.py serving guard).
EDITS_SET_ID = "edits"
#: img2img "change amount" the editor defaults to (matches the imagegen harness).
DENOISE_DEFAULT = 0.65


class EditError(ValueError):
    """A bad edit request (missing plate image, unknown candidate). Maps to HTTP 400."""


# --- io helpers -------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _library(cfg: Config, book: str) -> Path:
    return cfg.library_dir / book


def _edits_dir(cfg: Config, user: str, book: str) -> Path:
    return cfg.artsets_dir / user / book / EDITS_SET_ID


def _candidates_dir(cfg: Config, user: str, book: str) -> Path:
    # A sibling of edits/ so overlay manifests never see the scratch candidates.
    return cfg.artsets_dir / user / book / ".edit-candidates"


def _edits_json_path(cfg: Config, user: str, book: str) -> Path:
    return _edits_dir(cfg, user, book) / "edits.json"


def _page_id_of(plate_id: str) -> str:
    return plate_id.split("-", 1)[0]


# --- lookups ----------------------------------------------------------------


def _require_meta(cfg: Config, book: str) -> dict:
    meta = _library(cfg, book) / "meta.json"
    if not meta.is_file():
        raise LookupError(f"book {book!r} is not published")
    return _read_json(meta)


def _prompt_doc(cfg: Config, book: str, plate_id: str) -> dict:
    p = _library(cfg, book) / "prompts" / f"{plate_id}.json"
    if not p.is_file():
        raise LookupError(f"no published plate {plate_id!r}")
    return _read_json(p)


def _load_edits(cfg: Config, user: str, book: str) -> dict:
    p = _edits_json_path(cfg, user, book)
    return _read_json(p) if p.is_file() else {}


def _rev_of(stem: str, plate_id: str) -> int:
    """The ``-rN`` revision a plate filename stem encodes for ``plate_id`` (base = 1), or 0 if it is
    not this plate's image."""
    if stem == plate_id:
        return 1
    prefix = f"{plate_id}-r"
    if stem.startswith(prefix) and stem[len(prefix):].isdigit():
        return int(stem[len(prefix):])
    return 0


def _current_plate_png(cfg: Config, user: str, book: str, plate_id: str) -> bytes:
    """The image the editor starts from: the profile's prior overlay edit if any, else the book's
    current (highest ``-rN``) archival plate. Raises :class:`EditError` if none exists."""
    overlay = _edits_dir(cfg, user, book) / "images" / "plates" / f"{plate_id}.png"
    if overlay.is_file():
        return overlay.read_bytes()
    plates = _library(cfg, book) / "images" / "plates"
    best_path: Path | None = None
    best_rev = 0
    if plates.is_dir():
        for f in plates.glob(f"{plate_id}*.png"):
            rev = _rev_of(f.stem, plate_id)
            if rev > best_rev:
                best_rev, best_path = rev, f
    if best_path is None:
        raise EditError(f"no image on disk for plate {plate_id!r}")
    return best_path.read_bytes()


def _current_caption(cfg: Config, user: str, book: str, plate_id: str) -> str:
    """The caption to pre-fill: a prior overlay caption if present, else the page's auto-derived
    ``best_visual_beat`` (only the base plate carries one; extras get an empty caption)."""
    existing = _load_edits(cfg, user, book).get("plates", {}).get(plate_id)
    if existing is not None:
        return str(existing.get("caption", ""))
    if "-" in plate_id:
        return ""
    page = _library(cfg, book) / "pages" / f"{_page_id_of(plate_id)}.json"
    if not page.is_file():
        return ""
    ledger = _read_json(page).get("ledger") or {}
    return str(ledger.get("best_visual_beat") or "").strip()


# --- public API -------------------------------------------------------------


def plate_context(cfg: Config, user: str, book: str, plate_id: str) -> dict:
    """The editor pre-fill for one plate: subject prompt, negative, seed, size, current caption."""
    _require_meta(cfg, book)
    doc = _prompt_doc(cfg, book, plate_id)
    spec = _asset_spec(_edits_dir(cfg, user, book), plate_id)
    params = (doc.get("render") or {}).get("params_echo") or {}
    prompt = doc.get("final_subject_prompt") or ((doc.get("derived") or {}).get("prompt") or "")
    return {
        "plate_id": plate_id,
        "prompt": prompt,
        "negative": doc.get("negative_prompt", ""),
        "seed": params.get("seed"),
        "width": int(params.get("width", spec.width)),
        "height": int(params.get("height", spec.height)),
        "denoise_default": DENOISE_DEFAULT,
        "caption": _current_caption(cfg, user, book, plate_id),
    }


async def generate_candidate(
    cfg: Config,
    user: str,
    book: str,
    plate_id: str,
    *,
    prompt: str,
    client: ImagegenClient,
    negative: str | None = None,
    seed: int | None = None,
    denoise: float | None = None,
) -> dict:
    """img2img-render a candidate from the current plate image; store in scratch; return its token.

    The candidate is NOT visible in the book until :func:`commit_edit`. Raises ``LookupError`` if
    the book/plate is unknown, :class:`EditError` if there is no image to start from, and propagates
    ``GpuUnavailable`` from the client.
    """
    meta = _require_meta(cfg, book)
    _prompt_doc(cfg, book, plate_id)  # 404 on an unknown plate
    spec = _asset_spec(_edits_dir(cfg, user, book), plate_id)
    init_png = _current_plate_png(cfg, user, book, plate_id)
    checkpoint = ((meta.get("bake") or {}).get("models") or {}).get("imagegen")
    checkpoint = checkpoint if checkpoint and checkpoint != "unknown" else None
    dz = DENOISE_DEFAULT if denoise is None else float(denoise)

    png = await client.txt2img(
        prompt,
        negative or "",
        spec.width,
        spec.height,
        seed,
        checkpoint=checkpoint,
        init_image=init_png,
        denoise=dz,
    )

    token = secrets.token_hex(8)
    cand = _candidates_dir(cfg, user, book) / f"{token}.png"
    cand.parent.mkdir(parents=True, exist_ok=True)
    cand.write_bytes(png)
    # Record the params the candidate was made with, so commit records them in edits.json.
    _write_json(
        cand.with_suffix(".json"),
        {"prompt": prompt, "seed": seed, "denoise": dz},
    )
    return {"token": token, "width": spec.width, "height": spec.height}


def candidate_path(cfg: Config, user: str, book: str, token: str) -> Path:
    return _candidates_dir(cfg, user, book) / f"{token}.png"


def commit_edit(
    cfg: Config, user: str, book: str, plate_id: str, *, token: str, caption: str
) -> dict:
    """Promote a candidate into the overlay + record the edit and caption. Writes under artsets/.

    Raises ``LookupError`` if the book/plate is unknown, :class:`EditError` for a bad candidate.
    """
    meta = _require_meta(cfg, book)
    _prompt_doc(cfg, book, plate_id)  # 404 on an unknown plate
    cand = candidate_path(cfg, user, book, token)
    if not cand.is_file():
        raise EditError(f"no such candidate {token!r}")
    cand_meta = _read_json(cand.with_suffix(".json")) if cand.with_suffix(".json").is_file() else {}

    edits_dir = _edits_dir(cfg, user, book)
    spec = _asset_spec(edits_dir, plate_id)
    spec.src.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(cand), spec.src)  # the archival overlay PNG (used as the next re-edit's source)
    make_derivatives(spec.src, spec.web, spec.thumb, web_max_width=spec.web_max)
    cand.with_suffix(".json").unlink(missing_ok=True)

    source_rev = int(meta.get("revision", 1))
    edits = _load_edits(cfg, user, book)
    edits["book_id"] = book
    edits["user_id"] = user
    edits["source_revision"] = source_rev
    plates = edits.setdefault("plates", {})
    plates[plate_id] = {
        "caption": caption,
        "prompt": str(cand_meta.get("prompt", "")),
        "seed": cand_meta.get("seed"),
        "denoise": cand_meta.get("denoise"),
        "created": _now_iso(),
    }
    schemas.validate("artset-edits", edits)
    _write_json(_edits_json_path(cfg, user, book), edits)

    # Rebuild the overlay manifest so the reader can check it out. edits.json is not a book
    # reader-required file, so add it explicitly (captions must reach the device for offline).
    manifest = build_manifest(edits_dir, book, source_rev)
    if "edits.json" not in manifest["reader_required"]:
        extra = next((f["bytes"] for f in manifest["files"] if f["path"] == "edits.json"), 0)
        manifest["reader_required"].append("edits.json")
        manifest["total_bytes_reader"] += extra
    schemas.validate("manifest", manifest)
    _write_json(edits_dir / "manifest.json", manifest)
    return {"plate_id": plate_id, "caption": caption, "source_revision": source_rev}
