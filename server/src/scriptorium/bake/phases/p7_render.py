"""P7 — the real render phase (DESIGN §10, §7.4; ADR-0009, ADR-0011).

Turns every approved plate into pixels. Two phases, mirroring the P5 enter/GPU split (a GPU phase's
``from_state`` must be a GPU state):

- :class:`RenderEnter` — CPU claim ``approved → rendering`` (zero units), like
  :class:`~scriptorium.bake.phases.p5_prompts.PromptsEnter`.
- :class:`Render` — GPU phase ``rendering → rendered``. Its units are a **leading ``__unload__``
  pseudo-unit** followed by one unit per drafted plate (page plates + ``cover`` + ``portrait-*``).

The leading unload unit is the §7.4 / ADR-0009 GPU handoff: it calls TTS ``POST /v1/models/unload``
(**require success** — a failure means the GPU box is not usable → ``GpuUnavailable`` → the job
parks on ``waiting_gpu`` and retries), then probes imagegen ``health()``; if imagegen is down it
likewise parks. Because it runs before any plate unit and re-runs on every phase entry, TTS is
always unloaded before SDXL touches the GPU — the invariant is structural, not incidental.

Each plate unit style-wraps its prompt per §10 (page plates: ``style.prefix + final_subject_prompt
+ style.suffix``, ``negative = style.negative`` + ``derived.avoid``; the ``cover``/``portrait-*``
pseudo-plates are **pre-wrapped by P5** and pass through un-rewrapped), renders it at the asset size
(plate/cover 832×1216, portrait 1024×1024), writes the archival PNG, generates idempotent WebP
derivatives, and records ``wrapped_prompt``/``negative_prompt``/``render`` provenance on the plate's
``prompts/*.json``. Page-plate ``selection.json`` entries flip to ``rendered``. The job rests at
``rendered``; publish (``rendered → published``) is S10b.

The imagegen client is injected (``Render(client=...)``) so tests pass :class:`FakeImagegen`;
production builds a :class:`RealImagegenClient` from config. The single-worker runner (§7.4) plus
the unload-first unit are what keep LLM and render GPU work from ever interleaving.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ... import schemas
from ...render.derivatives import make_derivatives
from ...render.imagegen import ImagegenClient, RealImagegenClient
from ...styles import get_style
from ..job import Job, JobState
from ..tts_client import TtsClient
from .base import GpuUnavailable, Unit

# The leading pseudo-unit that unloads TTS + gates imagegen before any plate renders (§7.4). A
# non-numeric id that can never collide with a 4-digit page id or a cover/portrait pseudo-plate.
UNLOAD_UNIT_ID = "__unload__"

COVER_ID = "cover"
PORTRAIT_PREFIX = "portrait-"

# DESIGN §10 sizes: (render_w, render_h, web_max_w). Thumbs are a fixed 320w (see derivatives).
_PLATE_SIZE = (832, 1216, 1080)
_PORTRAIT_SIZE = (1024, 1024, 768)


# --- paths / io -------------------------------------------------------------


def _book_dir(cfg: Any, job: Job) -> Path:
    return cfg.work_dir / job.book_id


def _prompts_dir(cfg: Any, job: Job) -> Path:
    return _book_dir(cfg, job) / "prompts"


def _selection_path(cfg: Any, job: Job) -> Path:
    return _book_dir(cfg, job) / "selection.json"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _plate_ids(cfg: Any, job: Job) -> list[str]:
    """Every drafted plate id (page plates + cover/portrait pseudo-plates), stable order."""
    prompts = _prompts_dir(cfg, job)
    if not prompts.is_dir():
        return []
    return [p.stem for p in sorted(prompts.glob("*.json"))]


# --- per-asset layout + prompt assembly (DESIGN §4.2, §10) ------------------


@dataclass(frozen=True)
class _AssetSpec:
    src: Path  # archival full-res PNG
    web: Path  # reader web derivative
    thumb: Path  # reader thumb derivative
    width: int
    height: int
    web_max: int


def _asset_spec(book: Path, plate_id: str) -> _AssetSpec:
    """The §4.2 bundle paths and §10 sizes for one plate id (page / cover / portrait)."""
    images = book / "images"
    if plate_id == COVER_ID:
        w, h, web_max = _PLATE_SIZE
        return _AssetSpec(
            images / "cover.png", images / "web" / "cover.webp",
            images / "thumbs" / "cover.webp", w, h, web_max,
        )
    if plate_id.startswith(PORTRAIT_PREFIX):
        slug = plate_id[len(PORTRAIT_PREFIX):]
        w, h, web_max = _PORTRAIT_SIZE
        return _AssetSpec(
            images / "portraits" / f"{slug}.png", images / "web" / "portraits" / f"{slug}.webp",
            images / "thumbs" / "portraits" / f"{slug}.webp", w, h, web_max,
        )
    w, h, web_max = _PLATE_SIZE
    return _AssetSpec(
        images / "plates" / f"{plate_id}.png", images / "web" / "plates" / f"{plate_id}.webp",
        images / "thumbs" / "plates" / f"{plate_id}.webp", w, h, web_max,
    )


def _join_avoid(avoid: Any) -> str:
    """Normalise ``derived.avoid`` (a list or a pre-joined string) into a comma string (§10)."""
    if not avoid:
        return ""
    if isinstance(avoid, str):
        return avoid
    return ", ".join(str(a) for a in avoid)


def wrap_prompt(style: dict, plate_id: str, prompt_doc: dict) -> tuple[str, str]:
    """The §10 (wrapped, negative) strings for one plate.

    Page plates wrap ``style.prefix + final_subject_prompt + style.suffix`` and build the negative
    from ``style.negative`` + ``derived.avoid``. The ``cover``/``portrait-*`` pseudo-plates were
    fully assembled (style baked in) by P5, so their ``final_subject_prompt`` passes through and the
    negative is just ``style.negative`` (P7 must not re-wrap them — see p5_prompts docstring).
    """
    final = prompt_doc["final_subject_prompt"]
    if plate_id.isdigit():
        wrapped = f"{style['prefix']}{final}{style['suffix']}"
        avoid = _join_avoid((prompt_doc.get("derived") or {}).get("avoid"))
        negative = f"{style['negative']}, {avoid}" if avoid else style["negative"]
        return wrapped, negative
    return final, style["negative"]


def _default_seed(book_id: str, plate_id: str) -> int:
    """A stable per-plate seed, so re-rendering an unchanged plate reproduces its pixels (§10)."""
    digest = hashlib.sha256(f"{book_id}\x00{plate_id}".encode()).hexdigest()
    return int(digest[:8], 16)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _mark_rendered(cfg: Any, job: Job, page_id: str) -> None:
    """Flip a page plate's ``selection.json`` status to ``rendered`` (pixels now exist)."""
    path = _selection_path(cfg, job)
    if not path.is_file():
        return
    doc = _read_json(path)
    for plate in doc.get("plates", []):
        if plate["page_id"] == page_id and plate["status"] != "retired":
            plate["status"] = "rendered"
    _write_json(path, doc)


async def render_plate(
    cfg: Any, job: Job, plate_id: str, client: ImagegenClient, *, seed: int | None = None
) -> None:
    """Render one plate to PNG + derivatives and record its provenance (shared by P7 and regen).

    ``seed=None`` uses the deterministic per-plate seed; regen passes a fresh seed for new pixels.
    """
    book = _book_dir(cfg, job)
    prompt_path = _prompts_dir(cfg, job) / f"{plate_id}.json"
    doc = _read_json(prompt_path)
    style = get_style(job.bake_config["style_id"])
    wrapped, negative = wrap_prompt(style, plate_id, doc)
    spec = _asset_spec(book, plate_id)
    if seed is None:
        seed = _default_seed(job.book_id, plate_id)

    png = await client.txt2img(wrapped, negative, spec.width, spec.height, seed)
    spec.src.parent.mkdir(parents=True, exist_ok=True)
    spec.src.write_bytes(png)
    make_derivatives(spec.src, spec.web, spec.thumb, web_max_width=spec.web_max)

    prev_attempts = int((doc.get("render") or {}).get("attempts", 0))
    doc["wrapped_prompt"] = wrapped
    doc["negative_prompt"] = negative
    doc["render"] = {
        "at": _now_iso(),
        "params_echo": {"seed": seed, "width": spec.width, "height": spec.height},
        "attempts": prev_attempts + 1,
    }
    schemas.validate("prompt", doc)
    _write_json(prompt_path, doc)

    if plate_id.isdigit():
        _mark_rendered(cfg, job, plate_id)
    job.render_stub = False  # real pixels, not FakeImagegen placeholders


# --- phases -----------------------------------------------------------------


class RenderEnter:
    """Zero-unit CPU transition ``approved → rendering`` (the enter-running pattern)."""

    name = "render_enter"
    from_state = JobState.APPROVED
    to_state = JobState.RENDERING
    is_gpu = False

    def units(self, job: Job, cfg: Any) -> list[Unit]:
        return []

    def unit_done(self, job: Job, cfg: Any, unit: Unit) -> bool:  # pragma: no cover
        return True  # no units, so never consulted

    def run_unit(self, job: Job, cfg: Any, unit: Unit) -> None:  # pragma: no cover
        return None


class Render:
    """P7: unload TTS, then render each approved plate (rendering -> rendered)."""

    name = "p7_render"
    from_state = JobState.RENDERING
    to_state = JobState.RENDERED
    is_gpu = True

    def __init__(self, client: ImagegenClient | None = None) -> None:
        # Injected for tests (FakeImagegen); production builds the real client from config.
        self._injected = client

    def _client(self, cfg: Any) -> ImagegenClient:
        return self._injected if self._injected is not None else RealImagegenClient(cfg)

    def units(self, job: Job, cfg: Any) -> list[Unit]:
        return [Unit(id=UNLOAD_UNIT_ID)] + [Unit(id=pid) for pid in _plate_ids(cfg, job)]

    def unit_done(self, job: Job, cfg: Any, unit: Unit) -> bool:
        # The unload unit has no artifact — it must run on every phase entry (unload before render).
        if unit.id == UNLOAD_UNIT_ID:
            return False
        spec = _asset_spec(_book_dir(cfg, job), unit.id)
        return spec.src.is_file() and spec.web.is_file() and spec.thumb.is_file()

    async def run_unit(self, job: Job, cfg: Any, unit: Unit) -> None:
        if unit.id == UNLOAD_UNIT_ID:
            # §7.4 / ADR-0009: free the GPU of the LLM before SDXL, and require imagegen is up.
            await TtsClient(cfg).unload_models()  # raises GpuUnavailable on failure
            if not await self._client(cfg).health():
                raise GpuUnavailable("imagegen not reachable for render")
            return
        await render_plate(cfg, job, unit.id, self._client(cfg))
