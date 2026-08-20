"""P7 — the real render phase (DESIGN §10, §7.4; ADR-0011, ADR-0039).

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

Both GPU phases share :class:`_ImagegenPhase`: a **leading ``__unload__`` pseudo-unit** (name kept
for continuity) followed by one unit per plate id in that phase's set.

The leading unit is the imagegen-reachability gate: it probes imagegen ``health()`` and, if imagegen
is down, parks the job on ``waiting_gpu`` (``GpuUnavailable``) and retries. The old pre-render TTS
``POST /v1/models/unload`` handoff is gone — GPU exclusivity (LLM vs SDXL on one card) is now owned
server-side by a shared advisory GPU-tenancy lock, and each tenant frees its own VRAM before
releasing it (ADR-0039, supersedes ADR-0009). ``/health`` is never lock-covered, so this gate still
distinguishes a down service from a merely-busy one that a render call will block behind.

Each plate unit style-wraps its prompt per §10 (page plates: ``style.prefix + final_subject_prompt
+ style.suffix``, ``negative = style.negative`` + ``derived.avoid``; the ``cover``/``portrait-*``
pseudo-plates are **pre-wrapped by P5** and pass through un-rewrapped), renders it at the asset size
(plate/cover 832×1216, portrait 1024×1024), writes the archival PNG, generates idempotent WebP
derivatives, and records ``wrapped_prompt``/``negative_prompt``/``render`` provenance on the plate's
``prompts/*.json``. Page-plate ``selection.json`` entries flip to ``rendered``. The job rests at
``rendered``; publish (``rendered → published``) is S10b.

The imagegen client is injected (``Render(client=...)``) so tests pass :class:`FakeImagegen`;
production builds the configured backend from config (ADR-0038). The gate unit stays sequential
even when the plate units after it fan out, because only they are marked ``parallel``.
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
from ...render.imagegen import ImagegenClient, build_imagegen_client
from ...styles import resolve_style
from ..job import Job, JobState
from .base import GpuUnavailable, Unit

# The leading pseudo-unit that gates on imagegen reachability before any plate renders. A
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


# Appended to a *portrait* plate's negative only (ADR-0028). A portrait is the IP-Adapter reference
# for every plate its character anchors, so a two-figure portrait is not one bad picture — it is
# every plate that character appears on. `_GLOBAL_NEGATIVE`'s "duplicate, cloned face" targets one
# subject rendered twice; these target a deliberate second sitter.
_PORTRAIT_NEGATIVE = "two people, group portrait, diptych, multiple figures, couple"


def _is_portrait_plate(plate_id: str) -> bool:
    return plate_id.startswith(PORTRAIT_PREFIX)


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
    style: dict,
    plate_id: str,
    prompt_doc: dict,
    era: str | None = None,
    user_negative: str | None = None,
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

    ``user_negative`` is the book-wide negative the creator typed at bake time (ADR-0036). It is
    appended **last** so the style + global guardrails keep priority and ``_dedupe_terms`` drops any
    overlap. None/empty is a no-op — byte-identical to a pre-ADR-0036 render.
    """
    final = prompt_doc["final_subject_prompt"]
    if not _is_page_plate(plate_id):
        extra = _PORTRAIT_NEGATIVE if _is_portrait_plate(plate_id) else ""
        return final, _dedupe_terms(
            style["negative"], _GLOBAL_NEGATIVE, extra, user_negative or ""
        )

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
    negative = _dedupe_terms(
        style["negative"], _GLOBAL_NEGATIVE, _join_avoid(derived.get("avoid")), user_negative or ""
    )
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


# Conditioning for a plate whose frame holds more than one person (ADR-0028). IP-Adapter is
# global and unmasked — it has no way to apply a face to one figure and not the other — so on a
# two-person plate the second person inherits the anchor's face *and* clothes. 288 of 440 plates on
# the sample book were multi-figure. Full regional masking is ADR-0023 Phase 2; until then a
# multi-figure plate gets a weaker, later anchor so the prompt keeps control of the second figure.
_MULTI_FIGURE_STRENGTH = 0.35
_MULTI_FIGURE_START = 0.4


def reference_conditioning(depicted: list) -> tuple[float | None, float | None]:
    """``(strength, start)`` for a plate's reference — ``(None, None)`` to accept service defaults.

    A single-figure plate is what IP-Adapter is designed for and takes the service's tuned default.
    """
    if len(depicted or []) > 1:
        return _MULTI_FIGURE_STRENGTH, _MULTI_FIGURE_START
    return None, None


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
    checkpoint: str | None = None,
    references: list[bytes] | None = None,
    reference_strength: float | None = None,
    reference_start: float | None = None,
) -> None:
    """The pure render step: txt2img → write archival PNG → idempotent WebP derivatives.

    Shared by P7's :func:`render_plate` (work tree) and P8's post-publish regen (library tree,
    ``-rN`` variants). It touches only the three files in ``spec`` — no prompt/selection
    bookkeeping. ``style`` is the imagegen preset name (from ``styles.json`` ``imagegen_style``),
    or ``None`` for prompt-only styles (ADR-0013). ``references`` are optional portrait PNGs fed as
    image-prompt conditioning for character consistency (ADR-0023); ``None`` = prompt-only.
    ``reference_strength``/``reference_start`` tune that conditioning (ADR-0028); ``None`` accepts
    the service's defaults.
    """
    png = await client.txt2img(
        wrapped,
        negative,
        spec.width,
        spec.height,
        seed,
        style=style,
        checkpoint=checkpoint,
        references=references,
        reference_strength=reference_strength,
        reference_start=reference_start,
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
    style = resolve_style(job.bake_config)
    wrapped, negative = wrap_prompt(
        style, plate_id, doc, job.bake_config.get("era"), job.bake_config.get("negative")
    )
    spec = _asset_spec(book, plate_id)
    if seed is None:
        seed = _default_seed(job.book_id, plate_id)

    references, reference_slug = _portrait_reference(cfg, job, plate_id, doc)
    strength, start = reference_conditioning((doc.get("derived") or {}).get("depicted") or [])
    await render_to_spec(
        client,
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

    prev_attempts = int((doc.get("render") or {}).get("attempts", 0))
    doc["wrapped_prompt"] = wrapped
    doc["negative_prompt"] = negative
    # A backend that reports what it actually did folds that in beside the seed and
    # size. The Runpod worker returns its own render_s/model_load_s/total_s, the card
    # it ran on, and the sampler settings the graph was built with.
    #
    # This is how per-plate timing survives a fan-out. The external timing tool
    # attributes ComfyUI log lines to plates by "last render finishing before this
    # plate's render.at", which is only sound while renders are serial; concurrent
    # plates would be mis-attributed and the counts would still add up, so nothing
    # would flag it. A number the renderer reports about itself needs no attribution.
    #
    # ``params_echo`` is schema-declared opaque ("shape owned by the imagegen
    # service"), so this needs no schema change and no type regeneration.
    echo = {"seed": seed, "width": spec.width, "height": spec.height}
    echo.update(getattr(client, "last_echo", None) or {})
    doc["render"] = {
        "at": _now_iso(),
        "params_echo": echo,
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

    Both portrait and page render require imagegen is up (ADR-0039: the server-side GPU lock owns
    LLM/SDXL exclusivity); both render a plate id via :func:`render_plate`. Only the *set* of
    plate ids differs, so subclasses override :meth:`_plate_ids_for`.
    """

    is_gpu = True
    gpu_kind = "image"  # a render phase; the server-side GPU lock coordinates LLM/SDXL sharing

    def __init__(self, client: ImagegenClient | None = None) -> None:
        # Injected for tests (FakeImagegen); production builds the real client from config.
        self._injected = client

    def _client(self, cfg: Any) -> ImagegenClient:
        return self._injected if self._injected is not None else build_imagegen_client(cfg)

    def _plate_ids_for(self, job: Job, cfg: Any) -> list[str]:  # pragma: no cover - overridden
        raise NotImplementedError

    def units(self, job: Job, cfg: Any) -> list[Unit]:
        # ``__unload__`` is NOT parallel: it gates on imagegen being up, which must be
        # settled before any plate draws. The plates are, so the runner may overlap them
        # when the backend is a worker pool. At concurrency 1 the flag has no effect at all.
        return [Unit(id=UNLOAD_UNIT_ID)] + [
            Unit(id=pid, parallel=True) for pid in self._plate_ids_for(job, cfg)
        ]

    def unit_done(self, job: Job, cfg: Any, unit: Unit) -> bool:
        # The gate unit has no artifact — it must run on every phase entry (imagegen-up check).
        if unit.id == UNLOAD_UNIT_ID:
            return False
        spec = _asset_spec(_book_dir(cfg, job), unit.id)
        return spec.src.is_file() and spec.web.is_file() and spec.thumb.is_file()

    async def run_unit(self, job: Job, cfg: Any, unit: Unit) -> None:
        if unit.id == UNLOAD_UNIT_ID:
            # Require imagegen is up before drawing. The pre-render LLM unload is gone: the two GPU
            # services share a server-side tenancy lock and each frees its own VRAM before releasing
            # it, so /animate/generate just blocks on the lock rather than colliding with a resident
            # LLM (ADR-0039, supersedes ADR-0009). This gate stays — /health is never lock-covered.
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
        # When the owner asked to curate portraits (ADR-0025/0029), draw none up front — the review
        # screen generates/uploads them on demand so the gate starts blank. The leading __unload__
        # unit still runs (imagegen health gate), so render sequencing is unchanged. Any left
        # blank at approval are filled from their default prompt by :class:`Render` below.
        if job.bake_config.get("portrait_review"):
            return []
        return [p for p in _plate_ids(cfg, job) if p.startswith(PORTRAIT_PREFIX)]


class Render(_ImagegenPhase):
    """P7: render any still-blank portraits, then the cover + page plates (rendering -> rendered).

    Portraits are listed **first** so a page's IP-Adapter reference exists before the page draws.
    In the normal flow they already rendered in :class:`PortraitRender`, so existence-based
    ``unit_done`` skips them and the output is byte-identical. When the owner curated portraits
    (ADR-0029) only the *blanks* they never generated/uploaded are drawn here — from each portrait's
    current (possibly edited) default prompt — so approving with blanks matches the no-gate default
    and never overrides a portrait the owner already set up.
    """

    name = "p7_render"
    from_state = JobState.RENDERING
    to_state = JobState.RENDERED

    def _plate_ids_for(self, job: Job, cfg: Any) -> list[str]:
        ids = _plate_ids(cfg, job)
        portraits = [p for p in ids if p.startswith(PORTRAIT_PREFIX)]
        rest = [p for p in ids if not p.startswith(PORTRAIT_PREFIX)]
        return portraits + rest
