"""The picture-set render phase (DESIGN §8, ADR-0014).

A per-user "set" re-illustrates an already-published book in a chosen style (or a re-roll),
writing its images **outside** the immutable bundle at ``artsets/{user}/{book}/{set_id}/``. It runs
on the same single-worker runner as the book bake — so GPU exclusivity stays structural — but as a
self-contained side lifecycle: ``SET_RENDERING -> SET_DONE`` (see :mod:`scriptorium.bake.job`).

Sets are **images only**: which pages get illustrated, and where, lives in the book's shared
``selection.json`` and never changes. So this phase reads the book's resident, already-approved
prompts and re-renders them; it never touches ``library/{book}``, ``pages/*.json`` or the integrity
guard. To avoid the ``job.book_id``-rooted output dir of ``render_plate``, it reuses the render
**pure functions** (``wrap_prompt``, ``_asset_spec``, ``render_to_spec``, ``assemble_cover`` /
``assemble_portrait``) with the set dir as the explicit root.

Units, in order: a leading ``__unload__`` (identical to P7 — unload TTS, gate imagegen, else
``GpuUnavailable`` → ``waiting_gpu``), one per non-retired page plate, ``cover``, one
``portrait-{slug}`` per major character, and a trailing ``__finalize__`` that writes the manifest
and flips ``set.json`` to ``ready``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .. import schemas
from ..bake.job import Job, JobState
from ..bake.phases.base import GpuUnavailable, PipelineBug, Unit
from ..bake.phases.p5_prompts import (
    assemble_cover,
    assemble_portrait,
    cover_beat,
    eligible_portraits,
)
from ..bake.phases.p7_render import (
    COVER_ID,
    PORTRAIT_PREFIX,
    UNLOAD_UNIT_ID,
    _asset_spec,
    _is_page_plate,
    portrait_reference,
    reference_conditioning,
    render_to_spec,
    wrap_prompt,
)
from ..bake.phases.p8_publish import build_manifest
from ..bake.tts_client import TtsClient
from ..render.imagegen import ImagegenClient, RealImagegenClient
from ..styles import get_style

# Trailing pseudo-unit: writes the set manifest + flips set.json to ready. Non-numeric so it can
# never collide with a page-plate / cover / portrait id (same discipline as UNLOAD_UNIT_ID).
FINALIZE_UNIT_ID = "__finalize__"


# --- paths / io -------------------------------------------------------------


def _set_dir(cfg: Any, job: Job) -> Path:
    return cfg.artsets_dir / job.source["user"] / job.book_id / job.source["set_id"]


def _lib_dir(cfg: Any, job: Job) -> Path:
    return cfg.library_dir / job.book_id


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _page_plate_ids(cfg: Any, job: Job) -> list[str]:
    """Non-retired page-plate ids from the book's resident selection.json (effective id)."""
    sel = _read_json(_lib_dir(cfg, job) / "selection.json")
    return [
        p.get("plate_id") or p["page_id"]
        for p in sel.get("plates", [])
        if p.get("status") != "retired"
    ]


def _portrait_chars(cfg: Any, job: Job) -> list[dict]:
    """Major characters eligible for a portrait (mirrors P5), or [] if the book has no cast."""
    cast_path = _lib_dir(cfg, job) / "cast.json"
    return eligible_portraits(_read_json(cast_path)) if cast_path.is_file() else []


def _cast_chars(cfg: Any, job: Job) -> list[dict]:
    """The book's full cast (for depicted→slug resolution), or [] if it has none."""
    cast_path = _lib_dir(cfg, job) / "cast.json"
    return (_read_json(cast_path) or {}).get("characters", []) if cast_path.is_file() else []


def _era(cfg: Any, job: Job) -> str | None:
    """The book's period/place, read from the published bundle.

    A set job's own ``bake_config`` carries only ``style_id`` — the era lives in the bundle's
    ``meta.json`` (written at publish) — so without this a set would lose the period anchor that
    ADR-0026 adds to every page prompt.
    """
    meta_path = _lib_dir(cfg, job) / "meta.json"
    if not meta_path.is_file():
        return None
    return (_read_json(meta_path) or {}).get("era")


def _set_seed(book_id: str, set_id: str, plate_id: str) -> int:
    """Deterministic per-(book, set, plate) seed. Folding set_id in makes a re-roll differ."""
    digest = hashlib.sha256(f"{book_id}\x00{set_id}\x00{plate_id}".encode()).hexdigest()
    return int(digest[:8], 16)


def _picture_ids(cfg: Any, job: Job) -> list[str]:
    """Every picture a set renders — one portrait per major, then page plates + cover.

    The real work of ``SetRender.units()`` minus the ``__unload__`` / ``__finalize__`` pseudo-units,
    so ``len(...)`` is the picture total the reader shows ("… of N"). Portraits lead for the same
    reason P7 splits them into their own phase: a page plate is conditioned on its character's
    portrait (ADR-0023/0026), so that portrait must already exist in *this set*.
    """
    portraits = [f"{PORTRAIT_PREFIX}{c['slug']}" for c in _portrait_chars(cfg, job)]
    return [*portraits, *_page_plate_ids(cfg, job), COVER_ID]


def set_render_progress(cfg: Any, job: Job) -> tuple[int, int]:
    """``(done, total)`` pictures for a set-render job, for the reader's "Pictures" status.

    ``total`` comes from the book's stable ``selection.json`` + ``cast.json`` (NOT
    ``prompts/*.json``, which a set writes lazily as it renders — that would make total track done).
    ``done`` counts the pictures whose files exist, exactly as ``SetRender.unit_done`` does.
    """
    set_dir = _set_dir(cfg, job)
    ids = _picture_ids(cfg, job)
    done = 0
    for pid in ids:
        spec = _asset_spec(set_dir, pid)
        if spec.src.is_file() and spec.web.is_file() and spec.thumb.is_file():
            done += 1
    return done, len(ids)


# --- the phase --------------------------------------------------------------


class SetRender:
    """Render one per-user picture set (``set_rendering -> set_done``)."""

    name = "artset_render"
    from_state = JobState.SET_RENDERING
    to_state = JobState.SET_DONE
    is_gpu = True
    gpu_kind = "image"  # needs SDXL/ComfyUI resident — the runner must NOT free the image GPU here

    def __init__(self, client: ImagegenClient | None = None) -> None:
        # Injected for tests (FakeImagegen); production builds the real client from config.
        self._injected = client

    def _client(self, cfg: Any) -> ImagegenClient:
        return self._injected if self._injected is not None else RealImagegenClient(cfg)

    def units(self, job: Job, cfg: Any) -> list[Unit]:
        picture_ids = _picture_ids(cfg, job)  # portraits first — see _picture_ids
        return [
            Unit(id=UNLOAD_UNIT_ID),
            *(Unit(id=pid) for pid in picture_ids),
            Unit(id=FINALIZE_UNIT_ID),
        ]

    def unit_done(self, job: Job, cfg: Any, unit: Unit) -> bool:
        if unit.id == UNLOAD_UNIT_ID:
            return False  # no artifact — must re-run on every phase entry (unload before render)
        if unit.id == FINALIZE_UNIT_ID:
            return (_set_dir(cfg, job) / "manifest.json").is_file()
        spec = _asset_spec(_set_dir(cfg, job), unit.id)
        return spec.src.is_file() and spec.web.is_file() and spec.thumb.is_file()

    async def run_unit(self, job: Job, cfg: Any, unit: Unit) -> None:
        if unit.id == UNLOAD_UNIT_ID:
            # §7.4 / ADR-0009: free the GPU of the LLM before SDXL, and require imagegen is up.
            await TtsClient(cfg).unload_models()  # raises GpuUnavailable on failure
            if not await self._client(cfg).health():
                raise GpuUnavailable("imagegen not reachable for set render")
            return
        if unit.id == FINALIZE_UNIT_ID:
            self._finalize(cfg, job)
            return
        await self._render(cfg, job, unit.id)

    # --- rendering ----------------------------------------------------------

    async def _render(self, cfg: Any, job: Job, plate_id: str) -> None:
        set_dir = _set_dir(cfg, job)
        style = get_style(job.bake_config["style_id"])
        doc = self._prompt_doc(cfg, job, plate_id, style)
        wrapped, negative = wrap_prompt(style, plate_id, doc, _era(cfg, job))
        spec = _asset_spec(set_dir, plate_id)
        seed = _set_seed(job.book_id, job.source["set_id"], plate_id)
        # Condition on *this set's* portrait of the primary character (ADR-0023/0026). Before this
        # a set rendered entirely prompt-only, so every re-illustration lost character consistency.
        references, reference_slug = (None, None)
        if _is_page_plate(plate_id):
            references, reference_slug = portrait_reference(
                ((doc.get("derived") or {}).get("depicted")) or [],
                _cast_chars(cfg, job),
                set_dir / "images" / "portraits",
            )
        strength, start = reference_conditioning(
            ((doc.get("derived") or {}).get("depicted")) or []
        )
        await render_to_spec(
            self._client(cfg),
            wrapped,
            negative,
            spec,
            seed,
            style.get("imagegen_style"),
            checkpoint=job.bake_config.get("model"),
            references=references,
            reference_strength=strength,
            reference_start=start,
        )
        _write_json(
            set_dir / "prompts" / f"{plate_id}.json",
            {
                "plate_id": plate_id,
                "style_id": job.bake_config["style_id"],
                "wrapped_prompt": wrapped,
                "negative_prompt": negative,
                "seed": seed,
                "reference_slug": reference_slug,
            },
        )

    def _prompt_doc(self, cfg: Any, job: Job, plate_id: str, style: dict) -> dict:
        """The ``{final_subject_prompt, …}`` doc for one picture.

        Page plates reuse the book's approved, **style-neutral** prompt (``wrap_prompt`` then
        applies the set's style + the plate's ``avoid``). The cover/portrait pseudo-plates are
        re-assembled with the set's style (their strings bake the style in), exactly as P5 does.
        """
        lib = _lib_dir(cfg, job)
        if _is_page_plate(plate_id):
            return _read_json(lib / "prompts" / f"{plate_id}.json")
        if plate_id == COVER_ID:
            meta = _read_json(lib / "meta.json")
            pages = [_read_json(p) for p in sorted((lib / "pages").glob("*.json"))]
            final = assemble_cover(
                style, meta.get("title", ""), meta.get("author", ""), cover_beat(pages)
            )
            return {"final_subject_prompt": final}
        slug = plate_id[len(PORTRAIT_PREFIX):]
        char = next((c for c in _portrait_chars(cfg, job) if c["slug"] == slug), None)
        if char is None:  # pragma: no cover - units() only emits slugs that exist
            raise PipelineBug(f"no eligible portrait for slug {slug!r}")
        final = assemble_portrait(style, char["one_line"], char["visual_description"])
        return {"final_subject_prompt": final}

    def _finalize(self, cfg: Any, job: Job) -> None:
        set_dir = _set_dir(cfg, job)
        # Flip status BEFORE building the manifest so the manifest captures the ready set.json.
        set_json = set_dir / "set.json"
        doc = _read_json(set_json)
        doc["status"] = "ready"
        schemas.validate("artset", doc)
        _write_json(set_json, doc)
        manifest = build_manifest(
            set_dir, job.book_id, int(job.bake_config.get("source_revision", 1))
        )
        _write_json(set_dir / "manifest.json", manifest)
