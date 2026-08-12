"""P7 — the real render phase (DESIGN §10, §7.4; ADR-0009, ADR-0011).

Turns every approved plate into pixels. Render is split so **portraits draw first, in their own
phase**, with an optional human gate between them and the page plates (ADR-0025) — every page plate
is conditioned on its characters' portrait PNGs (ADR-0023), so the portraits must exist (and be
approved) before the pages draw. The phases (mirroring the P5 enter/GPU split — a GPU phase's
``from_state`` must be a GPU state):

- :class:`PortraitRenderEnter` — CPU claim ``approved → portraits_rendering`` (zero units).
- :class:`PortraitRender` — GPU phase ``portraits_rendering → portraits_review``; renders only the
  ``portrait-*`` plates. The job rests at ``portraits_review`` for the optional gate (or the runner
  auto-advances when the per-book ``portrait_review`` flag is off).
- :class:`Render` — GPU phase ``rendering → rendered``; renders the ``cover`` + page plates.

Both GPU phases share :class:`_ImagegenPhase`: a **leading ``__unload__`` pseudo-unit** followed by
one unit per plate id in that phase's set.

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
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ... import names, schemas
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

# A page-plate id: a bare 4-digit page id, or a '{page_id}-N' evenly-spaced extra (pictures per
# scene). These are style-wrapped and flip their selection entry to 'rendered'; the cover/portrait
# pseudo-plates (non-numeric) are not. NOTE: bare `.isdigit()` is False for '0007-2', so a compound
# plate would otherwise be mis-routed to the pseudo-plate path — always use this predicate.
_PAGE_PLATE = re.compile(r"^[0-9]{4}(-[0-9]+)?$")


def _is_page_plate(plate_id: str) -> bool:
    return bool(_PAGE_PLATE.match(plate_id))

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


# Composition language for ``derived.shot`` (ADR-0026). The transform has always emitted a shot
# type and P7 always threw it away, so person-centric beats rendered as landscapes with a speck
# (the M1 retro's headline composition finding) — and an IP-Adapter reference cannot express an
# identity on a 40-pixel face, which is why character conditioning never visibly helped.
_SHOT_TERMS = {
    "close": "close-up, head and shoulders, the figure fills the frame",
    "medium": "medium shot, figures large in the frame, waist up",
    "wide": "wide establishing shot",
}

# Appended to every style's negative (ADR-0026). SDXL's stock failure modes — a subject duplicated
# across the frame, mangled anatomy — and period slips were previously guarded only on
# `oil-painting`, added ad hoc. Terms already present in a style's own negative are de-duplicated.
_GLOBAL_NEGATIVE = (
    "duplicate, cloned face, two heads, extra limbs, extra fingers, deformed, mutated, "
    "bad anatomy, disfigured, crowd, extra people, "
    "modern clothing, contemporary dress, modern money, banknotes, paper currency, "
    "wristwatch, sunglasses"
)


def _dedupe_terms(*parts: str) -> str:
    """Join comma-separated prompt fragments, dropping repeats (first occurrence wins)."""
    seen: set[str] = set()
    out: list[str] = []
    for part in parts:
        for term in (t.strip() for t in (part or "").split(",")):
            if term and term.casefold() not in seen:
                seen.add(term.casefold())
                out.append(term)
    return ", ".join(out)


def wrap_prompt(
    style: dict, plate_id: str, prompt_doc: dict, era: str | None = None
) -> tuple[str, str]:
    """The §10 (wrapped, negative) strings for one plate.

    Page plates wrap ``style.prefix + [era] + final_subject_prompt + [shot] + style.suffix`` and
    build the negative from ``style.negative`` + :data:`_GLOBAL_NEGATIVE` + ``derived.avoid``. The
    ``cover``/``portrait-*`` pseudo-plates were fully assembled (style baked in) by P5, so their
    ``final_subject_prompt`` passes through and only the negative is extended (P7 must not re-wrap
    them — see p5_prompts docstring).

    ``era`` is the book's free-text period/place ("Russia 1870s"). Before ADR-0026 it reached only
    the text transforms, so the image model had no period anchor at all and fell back to its own
    priors — a Russian Orthodox "monk in a red coarse coat" renders as a Buddhist one.
    """
    final = prompt_doc["final_subject_prompt"]
    if not _is_page_plate(plate_id):
        return final, _dedupe_terms(style["negative"], _GLOBAL_NEGATIVE)

    derived = prompt_doc.get("derived") or {}
    # The subject is a sentence; drop its full stop so the style suffix reads as a continuation of
    # the comma-separated prompt rather than "...killed her father., canvas texture".
    subject = final.strip()
    if subject.endswith("."):
        subject = subject[:-1]
    era_seg = f"{era.strip()}, " if era and era.strip() else ""
    shot = _SHOT_TERMS.get(str(derived.get("shot") or "").strip().casefold(), "")
    shot_seg = f", {shot}" if shot else ""
    wrapped = f"{style['prefix']}{era_seg}{subject}{shot_seg}{style['suffix']}"
    negative = _dedupe_terms(style["negative"], _GLOBAL_NEGATIVE, _join_avoid(derived.get("avoid")))
    return wrapped, negative


# --- depicted-label → cast resolution (ADR-0026) ----------------------------

# Label folding is shared with cast reduction (scriptorium.names) so "Father Zossima" ≡ "Zossima"
# means the same thing in both places — disagreeing is how a plate gets anchored on the wrong face.
_tokens = names.tokens
_core_tokens = names.core_tokens


#: ``(exact, by_tokens)`` — the match tables :func:`resolve_character` reads.
CastIndex = tuple[dict[str, set[str]], list[tuple[frozenset, str]]]


def build_cast_index(characters: list[dict]) -> CastIndex:
    """``(exact, by_tokens)`` match tables over every name/alias the cast claims.

    A key claimed by two characters is *ambiguous* — the cast reducer can leave an alias shared
    between entries (ADR-0019/0022) — and resolution refuses it rather than guessing a face.
    """
    exact: dict[str, set[str]] = {}
    by_tokens: list[tuple[frozenset, str]] = []
    for c in characters:
        slug = c.get("slug")
        if not slug:
            continue
        for label in [c.get("name", ""), *(c.get("aliases") or [])]:
            for key in {" ".join(_tokens(label)), " ".join(_core_tokens(label))}:
                if key:
                    exact.setdefault(key, set()).add(slug)
            core = frozenset(_core_tokens(label))
            if core:
                by_tokens.append((core, slug))
    return exact, by_tokens


def resolve_character(label: Any, index: CastIndex) -> str | None:
    """The cast slug a depicted label names, or ``None`` when unknown or ambiguous."""
    exact, by_tokens = index
    for key in (" ".join(_tokens(label)), " ".join(_core_tokens(label))):
        slugs = exact.get(key) if key else None
        if slugs:
            return next(iter(slugs)) if len(slugs) == 1 else None
    # Fall back to a token-subset match so a fuller or descriptive label still finds its character
    # ("Pyotr Ilyitch Karamazov" → pyotr-ilyitch). Most specific wins; a tie between two different
    # characters is ambiguous and resolves to nothing.
    have = set(_core_tokens(label))
    if not have:
        return None
    hits = [(len(toks), slug) for toks, slug in by_tokens if toks <= have]
    if not hits:
        return None
    top = max(n for n, _ in hits)
    winners = {slug for n, slug in hits if n == top}
    return next(iter(winners)) if len(winners) == 1 else None


def portrait_reference(
    depicted: list, characters: list[dict], portraits_dir: Path
) -> tuple[list[bytes] | None, str | None]:
    """``(reference bytes, slug)`` for the **primary** depicted character, else ``(None, None)``.

    ADR-0023 specifies "primary character only", but the original loop took the *first depicted
    label that happened to resolve and have a portrait* — so whenever the real subject was a minor
    (no portrait) or the transform invented a name, a **secondary** character's face silently
    became the whole plate's identity anchor. That is what drew two monks for "Nastasya kneels
    before the elder" and two Madame Hohlakovs for "Pyotr Ilyitch sits while she shrieks".

    ADR-0026 makes it literal: resolve the primary label only; if it does not resolve, or has no
    portrait, render prompt-only rather than anchoring on someone else.
    """
    if not depicted:
        return None, None
    slug = resolve_character(depicted[0], build_cast_index(characters))
    if not slug:
        return None, None
    png = portraits_dir / f"{slug}.png"
    if not png.is_file():
        return None, None
    return [png.read_bytes()], slug


def _portrait_reference(
    cfg: Any, job: Job, plate_id: str, doc: dict
) -> tuple[list[bytes] | None, str | None]:
    """:func:`portrait_reference` against the work tree (page plates only)."""
    if not _is_page_plate(plate_id):
        return None, None
    book = _book_dir(cfg, job)
    cast_path = book / "cast.json"
    if not cast_path.is_file():
        return None, None
    characters = (_read_json(cast_path) or {}).get("characters", [])
    depicted = ((doc.get("derived") or {}).get("depicted")) or []
    return portrait_reference(depicted, characters, book / "images" / "portraits")


def _default_seed(book_id: str, plate_id: str) -> int:
    """A stable per-plate seed, so re-rendering an unchanged plate reproduces its pixels (§10)."""
    digest = hashlib.sha256(f"{book_id}\x00{plate_id}".encode()).hexdigest()
    return int(digest[:8], 16)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _mark_rendered(cfg: Any, job: Job, plate_id: str) -> None:
    """Flip a single plate's ``selection.json`` status to ``rendered`` (pixels now exist).

    Matches on the plate's effective id (``plate_id`` when present, else ``page_id``), so a page's
    evenly-spaced extras are marked independently of its base plate.
    """
    path = _selection_path(cfg, job)
    if not path.is_file():
        return
    doc = _read_json(path)
    for plate in doc.get("plates", []):
        if plate.get("plate_id", plate["page_id"]) == plate_id and plate["status"] != "retired":
            plate["status"] = "rendered"
    _write_json(path, doc)


async def render_to_spec(
    client: ImagegenClient,
    wrapped: str,
    negative: str,
    spec: _AssetSpec,
    seed: int,
    style: str | None = None,
    references: list[bytes] | None = None,
) -> None:
    """The pure render step: txt2img → write archival PNG → idempotent WebP derivatives.

    Shared by P7's :func:`render_plate` (work tree) and P8's post-publish regen (library tree,
    ``-rN`` variants). It touches only the three files in ``spec`` — no prompt/selection
    bookkeeping. ``style`` is the imagegen preset name (from ``styles.json`` ``imagegen_style``),
    or ``None`` for prompt-only styles (ADR-0013). ``references`` are optional portrait PNGs fed as
    image-prompt conditioning for character consistency (ADR-0023); ``None`` = prompt-only.
    """
    png = await client.txt2img(
        wrapped, negative, spec.width, spec.height, seed, style=style, references=references
    )
    spec.src.parent.mkdir(parents=True, exist_ok=True)
    spec.src.write_bytes(png)
    make_derivatives(spec.src, spec.web, spec.thumb, web_max_width=spec.web_max)


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
    wrapped, negative = wrap_prompt(style, plate_id, doc, job.bake_config.get("era"))
    spec = _asset_spec(book, plate_id)
    if seed is None:
        seed = _default_seed(job.book_id, plate_id)

    references, reference_slug = _portrait_reference(cfg, job, plate_id, doc)
    await render_to_spec(
        client, wrapped, negative, spec, seed, style.get("imagegen_style"), references=references
    )

    prev_attempts = int((doc.get("render") or {}).get("attempts", 0))
    doc["wrapped_prompt"] = wrapped
    doc["negative_prompt"] = negative
    doc["render"] = {
        "at": _now_iso(),
        "params_echo": {"seed": seed, "width": spec.width, "height": spec.height},
        "attempts": prev_attempts + 1,
        # Which face conditioned this plate (ADR-0026) — previously invisible, so a plate anchored
        # on the wrong character could only be found by eye.
        "reference_slug": reference_slug,
    }
    schemas.validate("prompt", doc)
    _write_json(prompt_path, doc)

    if _is_page_plate(plate_id):
        _mark_rendered(cfg, job, plate_id)
    job.render_stub = False  # real pixels, not FakeImagegen placeholders


# --- phases -----------------------------------------------------------------


class PortraitRenderEnter:
    """Zero-unit CPU transition ``approved → portraits_rendering`` (the enter-running pattern).

    Portraits render in their own phase (before the page plates) so an optional human gate can
    inspect them mid-bake (ADR-0025). When no gate is wanted the job flows straight through.
    """

    name = "portrait_render_enter"
    from_state = JobState.APPROVED
    to_state = JobState.PORTRAITS_RENDERING
    is_gpu = False

    def units(self, job: Job, cfg: Any) -> list[Unit]:
        return []

    def unit_done(self, job: Job, cfg: Any, unit: Unit) -> bool:  # pragma: no cover
        return True  # no units, so never consulted

    def run_unit(self, job: Job, cfg: Any, unit: Unit) -> None:  # pragma: no cover
        return None


class _ImagegenPhase:
    """Shared machinery for the two GPU render phases: client injection + the ``__unload__`` unit.

    Both portrait and page render must (§7.4 / ADR-0009) free the GPU of the LLM before SDXL and
    require imagegen is up; both render a plate id via :func:`render_plate`. Only the *set* of
    plate ids differs, so subclasses override :meth:`_plate_ids_for`.
    """

    is_gpu = True
    gpu_kind = "image"  # needs SDXL/ComfyUI resident — the runner must NOT free the image GPU here

    def __init__(self, client: ImagegenClient | None = None) -> None:
        # Injected for tests (FakeImagegen); production builds the real client from config.
        self._injected = client

    def _client(self, cfg: Any) -> ImagegenClient:
        return self._injected if self._injected is not None else RealImagegenClient(cfg)

    def _plate_ids_for(self, job: Job, cfg: Any) -> list[str]:  # pragma: no cover - overridden
        raise NotImplementedError

    def units(self, job: Job, cfg: Any) -> list[Unit]:
        return [Unit(id=UNLOAD_UNIT_ID)] + [Unit(id=pid) for pid in self._plate_ids_for(job, cfg)]

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


class PortraitRender(_ImagegenPhase):
    """Render only the ``portrait-*`` plates (portraits_rendering -> portraits_review).

    Portraits render first because every page plate is conditioned on its characters' portrait
    PNGs (ADR-0023 / _portrait_reference). Resting at ``portraits_review`` lets an optional human
    gate approve/regenerate them before the page plates draw (ADR-0025).
    """

    name = "portrait_render"
    from_state = JobState.PORTRAITS_RENDERING
    to_state = JobState.PORTRAITS_REVIEW

    def _plate_ids_for(self, job: Job, cfg: Any) -> list[str]:
        return [p for p in _plate_ids(cfg, job) if p.startswith(PORTRAIT_PREFIX)]


class Render(_ImagegenPhase):
    """P7: render the cover + page plates (rendering -> rendered).

    Portraits already rendered in :class:`PortraitRender`; existence-based ``unit_done`` skips any
    that somehow reappear here, so this stays resumable and never double-renders a portrait.
    """

    name = "p7_render"
    from_state = JobState.RENDERING
    to_state = JobState.RENDERED

    def _plate_ids_for(self, job: Job, cfg: Any) -> list[str]:
        return [p for p in _plate_ids(cfg, job) if not p.startswith(PORTRAIT_PREFIX)]
