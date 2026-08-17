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
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import schemas
from ..bake.phases.p7_render import (
    _asset_spec,
    _AssetSpec,
    _is_page_plate,
    portrait_reference,
    reference_conditioning,
    wrap_prompt,
)
from ..bake.phases.p8_publish import _matches_any, build_manifest
from ..config import Config
from ..render.derivatives import make_derivatives
from ..render.imagegen import ImagegenClient
from ..styles import load_styles, resolve_style

#: The reserved set id the overlay is served under (see artsets/api.py serving guard).
EDITS_SET_ID = "edits"
#: The synthetic "base book" reader id (matches the reader's DEFAULT_SET_ID) — no set overlay.
DEFAULT_SET_ID = "default"
#: img2img "change amount" the editor defaults to. Kept low so an edit stays on-model (the whole
#: point of img2img here is to fix one thing, not repaint the plate into a different look).
DENOISE_DEFAULT = 0.45
#: Fallback style when a book/set records none (older bundles) — the catalog's empty "No style".
_FALLBACK_STYLE_ID = "none"
#: Default imagegen quality tier the editor pre-selects (matches the harness).
QUALITY_DEFAULT = "standard"


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


# --- active reader (base book, or the style set being viewed) ----------------
#
# An edit must reproduce the look of the reader the user is *actually viewing* (ADR-0033 layers the
# overlay over "whatever reader is active"). A style set re-illustrates the book under a different
# style + checkpoint, so editing a comic-set page must re-render comic, not fall back to the book's
# base look. These helpers resolve the active reader's style/model/init-image/portraits.


def _is_set(set_id: str | None) -> bool:
    """True iff ``set_id`` names a real style set (not the base book / the edits overlay)."""
    return bool(set_id) and set_id not in (DEFAULT_SET_ID, EDITS_SET_ID)


def _scope_of(set_id: str | None) -> str:
    """The overlay *scope* an edit belongs to (ADR-0035): a style set's own id, else ``"default"``
    for the base book. An edit only ever overrides the reader it was made from, so its image + entry
    are filed under this scope and switching sets shows that set's own picture."""
    return set_id if _is_set(set_id) else DEFAULT_SET_ID


def _scoped_spec(edits_dir: Path, plate_id: str, scope: str) -> _AssetSpec:
    """The overlay asset paths for one plate *within a scope* — the base spec with a ``{scope}/``
    segment inserted before each filename (``images/web/plates/{scope}/{plate_id}.webp``), so an
    edit made on the comic set and one made on the base book coexist as separate files."""
    spec = _asset_spec(edits_dir, plate_id)

    def scoped(p: Path) -> Path:
        return p.parent / scope / p.name

    return replace(spec, src=scoped(spec.src), web=scoped(spec.web), thumb=scoped(spec.thumb))


def _finalize_overlay_manifest(edits_dir: Path, book: str, source_rev: int) -> dict:
    """Build + write the overlay ``manifest.json``, tagging the overlay-only reader-required files.

    An overlay delivers two things a published BOOK never has, so they aren't in the shared
    ``READER_REQUIRED`` globs (each of which the bundle verifier requires to match a file): the
    captions (``edits.json``) and any accepted clips (``images/video/**``). We add those globs
    here — the video glob only when a clip exists — then recompute the reader byte total."""
    manifest = build_manifest(edits_dir, book, source_rev)
    extra = ["edits.json"]
    if any(f["path"].startswith("images/video/") for f in manifest["files"]):
        extra.append("images/video/**")
    for glob in extra:
        if glob not in manifest["reader_required"]:
            manifest["reader_required"].append(glob)
    required = tuple(manifest["reader_required"])
    manifest["total_bytes_reader"] = sum(
        f["bytes"] for f in manifest["files"] if _matches_any(f["path"], required)
    )
    schemas.validate("manifest", manifest)
    _write_json(edits_dir / "manifest.json", manifest)
    return manifest


def _video_path(edits_dir: Path, plate_id: str, scope: str) -> Path:
    """The overlay path for a plate's accepted clip within a scope (ADR-0037):
    ``images/video/plates/{scope}/{plate_id}.mp4`` — a `images/video/**` sibling of the image
    derivatives, delivered offline by the same manifest glob and served as ``video/mp4``."""
    return edits_dir / "images" / "video" / "plates" / scope / f"{plate_id}.mp4"


def _plate_scopes(edits: dict, plate_id: str) -> dict:
    """The ``{scope: entry}`` edits for one plate, tolerant of the pre-ADR-0035 flat shape
    (``plates[plate_id]`` was a single entry). A legacy flat entry has no scope key, so it can't be
    attributed to a reader — it is ignored (returns ``{}``) and dropped on the next commit."""
    entry = (edits.get("plates") or {}).get(plate_id)
    if not isinstance(entry, dict) or "caption" in entry:
        return {}
    return entry


def _normalized_plates(edits: dict) -> dict:
    """``plates`` with any legacy flat (un-scopeable) entries dropped — a one-time migration to the
    scoped shape so a mixed old/new ``edits.json`` still validates after the next commit."""
    plates = edits.get("plates") or {}
    return {pid: by_scope for pid, by_scope in plates.items() if _plate_scopes(edits, pid)}


def _set_json(cfg: Config, user: str, book: str, set_id: str) -> dict | None:
    p = cfg.artsets_dir / user / book / set_id / "set.json"
    return _read_json(p) if p.is_file() else None


def _set_dir_if_ready(cfg: Config, user: str, book: str, set_id: str | None) -> Path | None:
    """The active set's directory if it is a rendered set, else ``None`` (⇒ use the base book)."""
    if not _is_set(set_id):
        return None
    d = cfg.artsets_dir / user / book / set_id
    return d if (d / "manifest.json").is_file() else None


def _reader_bake_config(cfg: Config, meta: dict, user: str, book: str, set_id: str | None) -> dict:
    """The ``{style_id, custom_style, model}`` the active reader was rendered with.

    A style set carries its own style + checkpoint in ``set.json``; the base book carries them in
    ``meta.json`` (``style_id``/``custom_style`` and the publish-pinned ``bake.models.imagegen``).
    ``model == "unknown"`` (imagegen offline at publish) → ``None`` so the service default is used.
    """
    sj = _set_json(cfg, user, book, set_id) if _is_set(set_id) else None
    if sj is not None:
        style_id = sj.get("style_id")
        custom_style = sj.get("custom_style")
        model = sj.get("model")
    else:
        style_id = meta.get("style_id")
        custom_style = meta.get("custom_style")
        model = ((meta.get("bake") or {}).get("models") or {}).get("imagegen")
    model = model if model and model != "unknown" else None
    return {
        "style_id": style_id or _FALLBACK_STYLE_ID,
        "custom_style": custom_style,
        "model": model,
    }


def _cast_characters(cfg: Config, book: str) -> list[dict]:
    """The book's full cast (for depicted→slug reference resolution), or [] if it has none."""
    p = _library(cfg, book) / "cast.json"
    return (_read_json(p) or {}).get("characters", []) if p.is_file() else []


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


def _current_plate_png(
    cfg: Config, user: str, book: str, plate_id: str, set_id: str | None = None
) -> bytes:
    """The image the editor starts from (the img2img starting image), in priority order:

    1. the profile's prior overlay edit *for this scope* (so re-edits chain from the last result on
       the same reader),
    2. the **active set's** rendered plate, when a style set is being viewed — so an edit repaints
       the comic image the reader sees, not the book's base plate,
    3. the book's current (highest ``-rN``) archival plate.

    Raises :class:`EditError` if none exists.
    """
    overlay = _scoped_spec(_edits_dir(cfg, user, book), plate_id, _scope_of(set_id)).src
    if overlay.is_file():
        return overlay.read_bytes()
    set_dir = _set_dir_if_ready(cfg, user, book, set_id)
    if set_dir is not None:
        set_plate = set_dir / "images" / "plates" / f"{plate_id}.png"
        if set_plate.is_file():
            return set_plate.read_bytes()
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


def _current_caption(cfg: Config, user: str, book: str, plate_id: str, scope: str) -> str:
    """The caption to pre-fill: a prior overlay caption for this scope if present, else the page's
    auto-derived ``best_visual_beat`` (only the base plate has one; extras get an empty caption)."""
    existing = _plate_scopes(_load_edits(cfg, user, book), plate_id).get(scope)
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


def _style_catalog() -> list[dict]:
    """The pickable illustration styles ``[{id, name}]`` (the styles-catalog is the authority)."""
    return [{"id": s["id"], "name": s["name"]} for s in load_styles().get("styles", [])]


async def plate_context(
    cfg: Config,
    user: str,
    book: str,
    plate_id: str,
    *,
    set_id: str | None = None,
    client: ImagegenClient | None = None,
) -> dict:
    """The editor pre-fill for one plate, matched to the reader (base book or active set) in view.

    Returns the subject prompt + the active reader's style/model/negative so the editor opens
    already set to reproduce the look the user sees, plus the style catalog and installed-model list
    for the override pickers. A prior overlay edit takes precedence, so re-opening resumes it.
    """
    meta = _require_meta(cfg, book)
    doc = _prompt_doc(cfg, book, plate_id)
    spec = _asset_spec(_edits_dir(cfg, user, book), plate_id)
    params = (doc.get("render") or {}).get("params_echo") or {}
    subject = doc.get("final_subject_prompt") or ((doc.get("derived") or {}).get("prompt") or "")

    scope = _scope_of(set_id)
    reader_cfg = _reader_bake_config(cfg, meta, user, book, set_id)
    style = resolve_style(reader_cfg)
    _, wrapped_negative = wrap_prompt(style, plate_id, doc, meta.get("era"))

    prior = _plate_scopes(_load_edits(cfg, user, book), plate_id).get(scope) or {}

    def _prefer(key: str, fallback: Any) -> Any:
        return prior[key] if key in prior and prior[key] is not None else fallback

    depicted = (doc.get("derived") or {}).get("depicted") or []
    models = await client.models() if client is not None else {"models": [], "default": None}
    # Video (ADR-0037): which animate models the service reports ready, and any clip already
    # accepted for this scope (so the editor can pre-fill the motion prompt / show "has a clip").
    video = (
        await client.video_health() if client is not None else {"models": [], "reachable": False}
    )
    prior_video = prior.get("video") or None
    return {
        "plate_id": plate_id,
        "prompt": _prefer("prompt", subject),
        "negative": _prefer("negative", wrapped_negative),
        "seed": prior.get("seed", params.get("seed")),
        "width": int(params.get("width", spec.width)),
        "height": int(params.get("height", spec.height)),
        "denoise_default": _prefer("denoise", DENOISE_DEFAULT),
        "caption": _current_caption(cfg, user, book, plate_id, scope),
        # Style / model of the active reader (or the prior edit), + the override lists.
        "style_id": _prefer("style_id", reader_cfg["style_id"]),
        "custom_style": _prefer("custom_style", reader_cfg["custom_style"]),
        "model": _prefer("model", reader_cfg["model"]),
        "quality_default": _prefer("quality", QUALITY_DEFAULT),
        "styles": _style_catalog(),
        "models": models.get("models", []),
        "default_model": models.get("default"),
        # Whether this plate has a cast portrait to pin the character's likeness against.
        "has_cast_reference": _is_page_plate(plate_id) and bool(depicted),
        # Video: gate the editor's "Bring to life" section + its model picker; echo any prior clip.
        "video_available": bool(video.get("models")),
        "animate_models": video.get("models", []),
        "video": prior_video,
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
    set_id: str | None = None,
    style_id: str | None = None,
    custom_style: str | None = None,
    model: str | None = None,
    quality: str | None = None,
    use_cast_reference: bool = True,
    reference_image: bytes | None = None,
    reference_strength: float | None = None,
) -> dict:
    """img2img-render a candidate matched to the active reader; store in scratch; return its token.

    Reproduces the bake/art-set render assembly (:mod:`scriptorium.artsets.phase`): the subject
    prompt is style-wrapped with the resolved style (prefix/suffix + LoRA preset), rendered on the
    reader's checkpoint, and conditioned on the plate's character portrait so the edit stays on the
    book's look and on-model — the fix for edits reverting to the base checkpoint's raw style.

    The candidate is NOT visible in the book until :func:`commit_edit`. Raises ``LookupError`` if
    the book/plate is unknown, :class:`EditError` if there is no image to start from, and propagates
    ``GpuUnavailable`` from the client.
    """
    meta = _require_meta(cfg, book)
    base_doc = _prompt_doc(cfg, book, plate_id)  # 404 on an unknown plate; subject + derived
    spec = _asset_spec(_edits_dir(cfg, user, book), plate_id)
    init_png = _current_plate_png(cfg, user, book, plate_id, set_id)

    # Resolve style/model: an explicit picker choice overrides the active reader's own values.
    reader_cfg = _reader_bake_config(cfg, meta, user, book, set_id)
    bake_config = {
        "style_id": style_id or reader_cfg["style_id"],
        "custom_style": custom_style if custom_style is not None else reader_cfg["custom_style"],
        "model": model if model is not None else reader_cfg["model"],
    }
    style = resolve_style(bake_config)
    # Wrap the (possibly edited) subject with the active style, exactly as P7/the set render does.
    doc = {"final_subject_prompt": prompt, "derived": base_doc.get("derived") or {}}
    wrapped, wrapped_neg = wrap_prompt(style, plate_id, doc, meta.get("era"))
    neg = negative if negative is not None else wrapped_neg

    # Character likeness: an uploaded photo overrides; else the plate's cast portrait (ADR-0023).
    depicted = (base_doc.get("derived") or {}).get("depicted") or []
    references: list[bytes] | None = None
    if reference_image is not None:
        references = [reference_image]
    elif use_cast_reference and _is_page_plate(plate_id):
        set_dir = _set_dir_if_ready(cfg, user, book, set_id)
        portraits_dir = (
            (set_dir / "images" / "portraits")
            if set_dir is not None
            else _library(cfg, book) / "images" / "portraits"
        )
        references, _ = portrait_reference(depicted, _cast_characters(cfg, book), portraits_dir)
    default_strength, ref_start = reference_conditioning(depicted)
    strength = reference_strength if reference_strength is not None else default_strength

    dz = DENOISE_DEFAULT if denoise is None else float(denoise)
    q = quality or None

    png = await client.txt2img(
        wrapped,
        neg,
        spec.width,
        spec.height,
        seed,
        style=style.get("imagegen_style"),
        checkpoint=bake_config["model"],
        references=references,
        reference_strength=strength if references else None,
        reference_start=ref_start if references else None,
        init_image=init_png,
        denoise=dz,
        quality=q,
    )

    token = secrets.token_hex(8)
    cand = _candidates_dir(cfg, user, book) / f"{token}.png"
    cand.parent.mkdir(parents=True, exist_ok=True)
    cand.write_bytes(png)
    # Record the params the candidate was made with, so commit records them in edits.json. The
    # subject prompt (not the wrapped string) is stored so a re-edit pre-fills the editable field.
    _write_json(
        cand.with_suffix(".json"),
        {
            "prompt": prompt,
            "seed": seed,
            "denoise": dz,
            "negative": neg,
            "style_id": bake_config["style_id"],
            "custom_style": bake_config["custom_style"],
            "model": bake_config["model"],
            "quality": q,
            "reference_strength": strength if references else None,
            # The scope (base book or a style set) this edit belongs to, so commit files it there.
            "set_id": _scope_of(set_id),
        },
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
    scope = cand_meta.get("set_id") or DEFAULT_SET_ID

    edits_dir = _edits_dir(cfg, user, book)
    spec = _scoped_spec(edits_dir, plate_id, scope)
    spec.src.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(cand), spec.src)  # the archival overlay PNG (used as the next re-edit's source)
    make_derivatives(spec.src, spec.web, spec.thumb, web_max_width=spec.web_max)
    cand.with_suffix(".json").unlink(missing_ok=True)

    source_rev = int(meta.get("revision", 1))
    edits = _load_edits(cfg, user, book)
    edits["book_id"] = book
    edits["user_id"] = user
    edits["source_revision"] = source_rev
    # Migrate any legacy flat (pre-ADR-0035) plate entries out before writing the scoped shape.
    plates = _normalized_plates(edits)
    edits["plates"] = plates
    entry = {
        "caption": caption,
        "prompt": str(cand_meta.get("prompt", "")),
        "seed": cand_meta.get("seed"),
        "denoise": cand_meta.get("denoise"),
        "set_id": scope,
        "created": _now_iso(),
    }
    # Record the style/model/negative/quality the replacement was rendered with, so a later re-edit
    # resumes from them and the edit is self-describing (only when the candidate captured them).
    for key in ("negative", "style_id", "custom_style", "model", "quality", "reference_strength"):
        if cand_meta.get(key) is not None:
            entry[key] = cand_meta[key]
    plates.setdefault(plate_id, {})[scope] = entry
    schemas.validate("artset-edits", edits)
    _write_json(_edits_json_path(cfg, user, book), edits)

    # Rebuild the overlay manifest so the reader checks it out (captions + any clips reach offline).
    _finalize_overlay_manifest(edits_dir, book, source_rev)
    return {"plate_id": plate_id, "caption": caption, "source_revision": source_rev}


# --- video (ADR-0037): animate a plate's current picture into a short clip -----
#
# Mirrors the image edit flow: an animate render → a scratch candidate mp4 (+ sidecar) → accept
# promotes it into the overlay at images/video/plates/{scope}/{plate_id}.mp4 and records a `video`
# descriptor on the scoped edit entry. The clip animates the plate's CURRENT committed picture (the
# same `_current_plate_png` the img2img start frame uses): to animate an edit, accept the picture
# edit first. A video is additive and independent of the image edit — it never changes the picture.


def video_candidate_path(cfg: Config, user: str, book: str, token: str) -> Path:
    return _candidates_dir(cfg, user, book) / f"{token}.mp4"


async def generate_video_candidate(
    cfg: Config,
    user: str,
    book: str,
    plate_id: str,
    *,
    motion_prompt: str,
    client: ImagegenClient,
    set_id: str | None = None,
    model: str | None = None,
    negative: str | None = None,
    seed: int | None = None,
    frames: int | None = None,
    fps: int | None = None,
) -> dict:
    """Animate the plate's current picture into a scratch candidate clip; return its token.

    The start frame is :func:`_current_plate_png` for the active scope (prior edit → set plate →
    book plate). The candidate is NOT visible until :func:`commit_video`. Raises ``LookupError`` for
    an unknown book/plate, :class:`EditError` if there is no image to animate, and propagates
    ``GpuUnavailable`` from the client (→ HTTP 503).
    """
    _require_meta(cfg, book)
    _prompt_doc(cfg, book, plate_id)  # 404 on an unknown plate
    init_png = _current_plate_png(cfg, user, book, plate_id, set_id)

    mp4 = await client.animate(
        init_png,
        motion_prompt,
        model=model,
        negative=negative or "",
        seed=seed,
        frames=frames,
        fps=fps,
    )

    token = secrets.token_hex(8)
    cand = video_candidate_path(cfg, user, book, token)
    cand.parent.mkdir(parents=True, exist_ok=True)
    cand.write_bytes(mp4)
    _write_json(
        cand.with_suffix(".json"),
        {
            "kind": "video",
            "motion_prompt": motion_prompt,
            "model": model,
            "frames": frames,
            "fps": fps,
            "seed": seed,
            # The scope (base book or a style set) this clip belongs to, so commit files it there.
            "set_id": _scope_of(set_id),
        },
    )
    return {"token": token}


def commit_video(cfg: Config, user: str, book: str, plate_id: str, *, token: str) -> dict:
    """Promote a candidate clip into the overlay; record a ``video`` descriptor on the edit entry.

    If the plate has no image edit for this scope yet, a minimal entry is seeded from the CURRENT
    caption + subject prompt so only the video is added (the picture and caption stay unchanged).
    Raises ``LookupError`` for an unknown book/plate, :class:`EditError` for a bad candidate.
    """
    meta = _require_meta(cfg, book)
    doc = _prompt_doc(cfg, book, plate_id)  # 404 on an unknown plate
    cand = video_candidate_path(cfg, user, book, token)
    if not cand.is_file():
        raise EditError(f"no such video candidate {token!r}")
    cand_meta = _read_json(cand.with_suffix(".json")) if cand.with_suffix(".json").is_file() else {}
    scope = cand_meta.get("set_id") or DEFAULT_SET_ID

    edits_dir = _edits_dir(cfg, user, book)
    dst = _video_path(edits_dir, plate_id, scope)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(cand), dst)
    cand.with_suffix(".json").unlink(missing_ok=True)

    source_rev = int(meta.get("revision", 1))
    edits = _load_edits(cfg, user, book)
    edits["book_id"] = book
    edits["user_id"] = user
    edits["source_revision"] = source_rev
    plates = _normalized_plates(edits)
    edits["plates"] = plates

    # Preserve an existing image edit for this scope; otherwise seed a minimal, invisible entry
    # (current caption + subject prompt) so the required fields exist and nothing else changes.
    existing = plates.get(plate_id, {}).get(scope)
    if existing is not None:
        entry = dict(existing)
    else:
        derived = doc.get("derived") or {}
        subject = doc.get("final_subject_prompt") or derived.get("prompt") or ""
        entry = {
            "caption": _current_caption(cfg, user, book, plate_id, scope),
            "prompt": str(subject),
            "set_id": scope,
            "created": _now_iso(),
        }
    entry["video"] = {
        "motion_prompt": str(cand_meta.get("motion_prompt", "")),
        "model": cand_meta.get("model"),
        "frames": cand_meta.get("frames"),
        "fps": cand_meta.get("fps"),
        "seed": cand_meta.get("seed"),
        "created": _now_iso(),
    }
    plates.setdefault(plate_id, {})[scope] = entry
    schemas.validate("artset-edits", edits)
    _write_json(_edits_json_path(cfg, user, book), edits)

    # Rebuild the overlay manifest so the mp4 (images/video/**) + edits.json reach the device.
    _finalize_overlay_manifest(edits_dir, book, source_rev)
    return {"plate_id": plate_id, "source_revision": source_rev}
