"""P5 — prompt derivation (DESIGN §7.1, §4.3, §10; TTS §7.5, transform ``illustration-prompt``).

One ``illustration-prompt`` call per **selected** page (``status:"selected"`` in
``selection.json``), in any order, producing a draft ``prompts/{page_id}.json`` record whose
``derived`` is the transform output stored verbatim. Two CPU-assembled pseudo-plates ride along:
the **cover** (§10 frontispiece formula over the max-salience chapter-1 page's
``best_visual_beat``) and, when ``portraits_enabled``, one **portrait** per major character with a
canonical description. The pseudo-plates never call TTS — they are pure string assembly, so they
are string-tested exactly against §10.

Two phases, mirroring P1/P2/P3's enter/run split (a GPU phase's ``from_state`` must be a GPU state):

- :class:`PromptsEnter` — CPU claim ``selected → prompts_running`` (zero units), like
  :class:`~scriptorium.bake.phases.p3_ledger.LedgerEnter`.
- :class:`PromptsDerive` — GPU phase ``prompts_running → prompts_draft``. Its units are the
  selected pages **followed by trailing pseudo-units** ``cover`` and ``portrait-{slug}`` (the P3
  merge-unit pattern: non-numeric ids that can never collide with a 4-digit page id, and — being
  CPU-only — they are reached only after every page unit has succeeded or ladder-failed, parking
  on ``waiting_gpu`` first on a 503).

``illustration-prompt`` failures follow the runner taxonomy via :class:`TtsClient`: 503/connection
→ ``waiting_gpu`` (``prompts_running`` is a GPU state), 422 → ``failed_units`` (that page left
prompt-less, "can't be approved until regenerated" §7.3), 400/404/413 → job ``failed``. Any
``meta.warnings`` a page returns are recorded on ``job.prompt_warnings[page_id]`` for the S9 gate.

**Interpretation (DESIGN §10, documented — see CYCLE-LOG S8):** a pseudo-plate's
``final_subject_prompt`` is the *full* §10 formula string **including** the style prefix/suffix
(the portrait formula bakes ``style.portrait_prefix`` into the prompt, so the cover formula's
``style.prefix``/``suffix`` are part of the string too). ``wrapped_prompt``/``negative_prompt``
stay absent until P7. The hand-written S3 ``bundle/prompts/{cover,portrait-*}.json`` are stale
placeholders that predate these formulas; tests assert schema + cross-refs, not equality.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ... import schemas
from ...selection.segment import even_segments
from ...styles import resolve_style
from ..job import Job, JobState
from ..tts_client import TtsClient
from .base import Unit

TRANSFORM = "illustration-prompt"

# Trailing CPU pseudo-units (non-numeric ids can't collide with a 4-digit page id).
COVER_UNIT_ID = "cover"
PORTRAIT_PREFIX = "portrait-"

# TTS §7.5: cast entries only for characters in ``ledger.present``, capped at the 4 most
# mention-frequent (the options schema itself allows up to 6).
CAST_CAP = 4
# §10 portrait: condense the canonical visual_description to at most this many words.
PORTRAIT_MAX_WORDS = 60

# ADR-0028: framing that keeps a portrait to one figure. "bust composition" in every style's
# ``portrait_prefix`` proved too weak on its own — it constrains the crop, not the head count.
# A code constant rather than 16 copies in styles.json, mirroring p7_render's _GLOBAL_NEGATIVE.
PORTRAIT_SOLO = "single figure, one person, head and shoulders, plain background, "

# --- subject reduction (ADR-0028) -------------------------------------------
# Person nouns a canonical description opens with. Deliberately a closed list: an unknown noun
# leaves the description untouched, which is the pre-ADR-0028 behaviour (safe, not silently wrong).
_PERSON_NOUN = (
    r"man|woman|boy|girl|gentleman|lady|monk|priest|peasant|figure|fellow|person|child|"
    r"youth|servant|officer|doctor|student|beauty|widow|captain|clerk|soldier|nun|"
    r"schoolboy|landowner|merchant|maiden|elder|invalid|creature"
)
# "A young Russian gentleman", "An old man", "A twenty-seven-year-old man" — determiner, up to five
# modifiers (non-greedy, so the *first* person noun wins), the noun.
_LEAD_SUBJECT = re.compile(
    r"^\s*(?:a|an|the)\s+(?:[\w'-]+,?\s+){0,5}?(?:" + _PERSON_NOUN + r")s?\b", re.I
)
# Posture / locomotion — where a bust prompt turns into a scene prompt.
_NARRATIVE_VERB = re.compile(
    r"\s+(?:stands?|sits?|kneels?|walks?|runs?|leaps?|lies?|strides?|sways?|moves?|"
    r"rests?|hides?|stretch(?:es)?|paces?|steps?)\b",
    re.I,
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_PRONOUN_WEARS = re.compile(r"^(?:he|she|they)\s+wears?\b", re.I)
_PRONOUN_COPULA = re.compile(r"^(?:he|she|they)\s+(?:is|are|was|were)\b", re.I)
# Cutting at a narrative verb can leave a dangling connective ("...as he", "...clothing and").
_DANGLING = frozenset(
    "as while and or yet but who that which then when before after so for from with in on at to of "
    "he she they his her their it its".split()
)
# Shorter than this, a surviving clause is a fragment rather than a description.
_MIN_CLAUSE_WORDS = 3

_DEFAULT_PRESET_MISSING_BEAT = ""


# --- paths / io -------------------------------------------------------------


def _book_dir(cfg: Any, job: Job) -> Path:
    return cfg.work_dir / job.book_id


def _pages_dir(cfg: Any, job: Job) -> Path:
    return _book_dir(cfg, job) / "pages"


def _prompts_dir(cfg: Any, job: Job) -> Path:
    return _book_dir(cfg, job) / "prompts"


def _selection_path(cfg: Any, job: Job) -> Path:
    return _book_dir(cfg, job) / "selection.json"


def _cast_path(cfg: Any, job: Job) -> Path:
    return _book_dir(cfg, job) / "cast.json"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_pages(cfg: Any, job: Job) -> list[dict]:
    pages_dir = _pages_dir(cfg, job)
    if not pages_dir.is_dir():
        return []
    return [_read_json(p) for p in sorted(pages_dir.glob("*.json"))]


def _load_cast(cfg: Any, job: Job) -> dict:
    path = _cast_path(cfg, job)
    return _read_json(path) if path.is_file() else {"characters": []}


def _selected_plates(cfg: Any, job: Job) -> list[dict]:
    """The ``status:"selected"`` plates, in selection order, normalized to explicit ids.

    Each record is ``{plate_id, page_id, segment_index}``. ``plate_id`` is the filename stem: the
    bare ``page_id`` for a page's first/only illustration, or ``{page_id}-N`` for an evenly-spaced
    extra (pictures-per-scene, DESIGN §8).
    """
    path = _selection_path(cfg, job)
    if not path.is_file():
        return []
    doc = _read_json(path)
    return [
        {
            "plate_id": p.get("plate_id", p["page_id"]),
            "page_id": p["page_id"],
            "segment_index": int(p.get("segment_index", 0)),
        }
        for p in doc.get("plates", [])
        if p.get("status") == "selected"
    ]


def _segments_per_page(plates: list[dict]) -> dict[str, int]:
    """How many selected plates each page carries (= its segment count for even splitting)."""
    counts: dict[str, int] = {}
    for rec in plates:
        counts[rec["page_id"]] = counts.get(rec["page_id"], 0) + 1
    return counts


# --- pure assembly helpers (string-tested against DESIGN §10 / TTS §7.5) -----


def present_cast(cast_doc: dict, ledger: dict) -> list[dict]:
    """The ``cast`` option for a page: characters as ``{name, one_line, appearance?}`` (§7.5).

    A character is *present* if its canonical ``name`` or any ``alias`` appears in
    ``ledger.present``. Result is capped at :data:`CAST_CAP`, ordered by mention frequency
    (``len(mention_pages)`` desc) with the earliest first-mention page as the tie-break.

    ``appearance`` (ADR-0032) is the character's approved ``visual_description``, condensed to
    subject-less attribute clauses with the same helpers the portrait prompt uses
    (``subject_attributes(condense(...))``), so the scene LLM sees the reviewed appearance rather
    than only the short ``one_line``. Omitted when the character has no description (minors). How
    strongly the ``illustration-prompt`` transform uses it is owned by the TTS template.
    """
    present = set(ledger.get("present") or [])
    matched = [
        c
        for c in cast_doc.get("characters", [])
        if c["name"] in present or any(a in present for a in c.get("aliases", []))
    ]

    def _rank(c: dict) -> tuple[int, str]:
        pages = c.get("mention_pages") or []
        first = min(pages) if pages else "9999"
        return (-len(pages), first)

    matched.sort(key=_rank)
    return [_present_one(c) for c in matched[:CAST_CAP]]


def _present_one(c: dict) -> dict:
    """One character's scene-cast entry: ``{name, one_line}`` plus ``appearance`` when described."""
    entry = {"name": c["name"], "one_line": c["one_line"]}
    description = (c.get("visual_description") or "").strip()
    if description:
        appearance = subject_attributes(condense(description))
        if appearance:
            entry["appearance"] = appearance
    return entry


def illustration_options(page: dict, cast_doc: dict, era: str | None) -> dict:
    """Assemble the TTS ``illustration-prompt`` options for one page (§7.5)."""
    ledger = page.get("ledger") or {}
    options: dict[str, Any] = {"ledger": ledger, "cast": present_cast(cast_doc, ledger)}
    if era:
        options["era"] = era
    return options


def cover_beat(pages: list[dict]) -> str:
    """``best_visual_beat`` of the max-``visual_salience`` chapter-1 page (ties → earliest seq)."""
    ch1 = [p for p in pages if p.get("chapter") == 1]
    if not ch1:
        return _DEFAULT_PRESET_MISSING_BEAT
    best = max(
        ch1,
        key=lambda p: (float((p.get("ledger") or {}).get("visual_salience", 0.0)), -p["seq"]),
    )
    return (best.get("ledger") or {}).get("best_visual_beat", _DEFAULT_PRESET_MISSING_BEAT)


def assemble_cover(style: dict, title: str, author: str, beat: str) -> str:
    """The §10 cover (frontispiece) prompt string, assembled CPU-side (no LLM)."""
    return (
        f"{style['prefix']}frontispiece for the book '{title}' by {author}: "
        f"{beat}{style['suffix']}"
    )


def condense(text: str, max_words: int = PORTRAIT_MAX_WORDS) -> str:
    """Condense ``text`` to ≤ ``max_words`` words, truncating on a sentence boundary (§10).

    Short text is returned unchanged. Otherwise the first ``max_words`` words are kept and cut
    back to the last sentence-ending punctuation within them; if there is none, the hard word
    truncation stands.
    """
    words = text.split()
    if len(words) <= max_words:
        return text
    truncated = " ".join(words[:max_words])
    cut = max(truncated.rfind(mark) for mark in ".!?")
    return truncated[: cut + 1] if cut != -1 else truncated


def _strip_lead_subject(text: str) -> str:
    """Drop a leading ``A/An/The <modifiers> <person-noun>``; unchanged when there is none."""
    match = _LEAD_SUBJECT.match(text)
    if not match:
        return text
    # Never empty the description out — a bare noun phrase ("A young man.") keeps its original text
    # rather than contributing nothing.
    return text[match.end() :].lstrip(" ,;") or text


def _trim_dangling(text: str) -> str:
    """Drop trailing connectives/pronouns left behind by a mid-sentence cut."""
    words = text.rstrip(" ,;.").split()
    while words and words[-1].strip(",;").casefold() in _DANGLING:
        words.pop()
    return " ".join(words).rstrip(" ,;")


def _defuse_pronoun_subject(sentence: str) -> str:
    """``He wears X`` → ``wearing X``; ``She is X`` → ``X``. Possessives ("Her face…") stay put."""
    if _PRONOUN_WEARS.match(sentence):
        return "wearing " + _PRONOUN_WEARS.sub("", sentence).lstrip()
    if _PRONOUN_COPULA.match(sentence):
        return _PRONOUN_COPULA.sub("", sentence).lstrip()
    return sentence


def subject_attributes(text: str) -> str:
    """Reduce a ``visual_description`` to **attribute clauses with no subject of their own**.

    ``one_line`` and ``visual_description`` are each a complete subject noun phrase. Concatenated
    (the pre-ADR-0028 formula), SDXL reads them as *two people* — which is how Mitya's reference
    portrait became a painting of two officers, and how 84 plates conditioned on it became two
    officers too. 25 of 69 portrait prompts on that book named the subject 2-3 times.

    Three deterministic passes, each of which can only ever remove text:

    1. strip a leading ``A/An/The <adjectives> <person-noun>`` so the description contributes
       ``with golden hair`` rather than ``A young man with golden hair``;
    2. drop posture/locomotion clauses (``stands at medium height``, ``sits unmoved``) — a bust
       portrait has no room for them and they pull the frame out to a full scene;
    3. fold a later clause's pronoun subject into an attribute (``He wears X`` → ``wearing X``).
    """
    out: list[str] = []
    for sentence in _SENTENCE_SPLIT.split(_strip_lead_subject(text)):
        narrative = _NARRATIVE_VERB.search(sentence)
        clause = _trim_dangling(sentence[: narrative.start()] if narrative else sentence)
        clause = _trim_dangling(_defuse_pronoun_subject(clause))
        if not clause:
            continue
        # A *truncated* clause can be a stub ("of about fifty years", left over from "...stands
        # with a fair, long beard"); an intact short one is a real attribute ("of forty").
        if narrative and len(clause.split()) < _MIN_CLAUSE_WORDS:
            continue
        out.append(clause if out else clause[:1].lower() + clause[1:])
    return ", ".join(out)


def assemble_portrait(style: dict, one_line: str, visual_description: str) -> str:
    """The §10 portrait prompt string for one major character, assembled CPU-side (no LLM).

    ADR-0028: the subject is named **exactly once** (``one_line``); the canonical description is
    reduced to attribute clauses by :func:`subject_attributes`, and :data:`PORTRAIT_SOLO` states the
    single-figure framing that ``style.portrait_prefix``'s "bust composition" alone did not enforce.
    """
    subject = one_line.strip().rstrip(" .")
    attributes = subject_attributes(condense(visual_description))
    tail = f", {attributes}" if attributes else ""
    return f"{style['portrait_prefix']}{PORTRAIT_SOLO}{subject}{tail}"


def eligible_portraits(cast_doc: dict) -> list[dict]:
    """Major characters with a canonical (non-null) ``visual_description`` — the portrait set."""
    return [
        c
        for c in cast_doc.get("characters", [])
        if c.get("major") and c.get("visual_description")
    ]


def rederive_portrait_prompt(cfg: Any, job: Job, slug: str) -> bool:
    """Re-assemble a portrait's ``derived.prompt`` from the current cast description (ADR-0025).

    Used when a human edits a character's ``visual_description``/``one_line`` at the portrait gate:
    the auto-assembled prompt is recomputed so a subsequent regenerate reflects the edit. A manual
    ``edited_prompt`` override (set via the prompt lever) still wins for ``final_subject_prompt`` —
    explicit prompt edits take precedence over description-derived ones until reverted. Returns True
    if a portrait prompt file existed and was rewritten, False otherwise (no-op — not a portrait, or
    no description yet).
    """
    path = _prompts_dir(cfg, job) / f"{PORTRAIT_PREFIX}{slug}.json"
    if not path.is_file():
        return False
    char = next(
        (c for c in _load_cast(cfg, job).get("characters", []) if c.get("slug") == slug),
        None,
    )
    if char is None or not char.get("visual_description"):
        return False
    style = resolve_style(job.bake_config)
    doc = _read_json(path)
    prompt = assemble_portrait(style, char["one_line"], char["visual_description"])
    doc["derived"] = {"prompt": prompt}
    doc["final_subject_prompt"] = (
        doc["edited_prompt"] if doc.get("edited_prompt") is not None else prompt
    )
    schemas.validate("prompt", doc)
    _write_json(path, doc)
    return True


def _draft(page_id: str, prompt: str, derived: dict | None = None) -> dict:
    """A draft prompt record (P5): ``derived`` verbatim, no edit, computed final subject."""
    return {
        "page_id": page_id,
        "derived": derived if derived is not None else {"prompt": prompt},
        "edited_prompt": None,
        "final_subject_prompt": prompt,
    }


def _title(job: Job) -> str:
    return job.bake_config.get("title") or job.title or ""


def _author(job: Job) -> str:
    return job.bake_config.get("author") or (job.source or {}).get("author") or ""


def _portraits_enabled(job: Job) -> bool:
    return bool(job.bake_config.get("portraits_enabled", True))


# --- phases -----------------------------------------------------------------


class PromptsEnter:
    """Zero-unit CPU transition ``selected → prompts_running`` (the enter-running pattern)."""

    name = "prompts_enter"
    from_state = JobState.SELECTED
    to_state = JobState.PROMPTS_RUNNING
    is_gpu = False

    def units(self, job: Job, cfg: Any) -> list[Unit]:
        return []

    def unit_done(self, job: Job, cfg: Any, unit: Unit) -> bool:  # pragma: no cover
        return True  # no units, so never consulted

    def run_unit(self, job: Job, cfg: Any, unit: Unit) -> None:  # pragma: no cover
        return None


class PromptsDerive:
    """P5: derive an illustration prompt per selected page, plus cover + portrait pseudo-plates."""

    name = "p5_prompts"
    from_state = JobState.PROMPTS_RUNNING
    to_state = JobState.PROMPTS_DRAFT
    is_gpu = True

    def units(self, job: Job, cfg: Any) -> list[Unit]:
        # Selected plates (GPU/TTS) — one unit per plate id, so a page's evenly-spaced extras
        # (`0007-2`, …) are their own units — then the CPU pseudo-plates. Cover is always produced;
        # portraits only when enabled. Trailing order mirrors P3's merge unit.
        units = [Unit(id=rec["plate_id"]) for rec in _selected_plates(cfg, job)]
        units.append(Unit(id=COVER_UNIT_ID))
        if _portraits_enabled(job):
            units += [
                Unit(id=f"{PORTRAIT_PREFIX}{c['slug']}")
                for c in eligible_portraits(_load_cast(cfg, job))
            ]
        return units

    def unit_done(self, job: Job, cfg: Any, unit: Unit) -> bool:
        path = _prompts_dir(cfg, job) / f"{unit.id}.json"
        if not path.is_file():
            return False
        try:
            _read_json(path)
            return True
        except json.JSONDecodeError:
            return False

    async def run_unit(self, job: Job, cfg: Any, unit: Unit) -> None:
        if unit.id == COVER_UNIT_ID:
            self._write_cover(cfg, job)
            return
        if unit.id.startswith(PORTRAIT_PREFIX):
            self._write_portrait(cfg, job, unit.id)
            return
        await self._derive_plate(cfg, job, unit.id)

    # --- per-plate LLM derivation ------------------------------------------

    async def _derive_plate(self, cfg: Any, job: Job, plate_id: str) -> None:
        """Derive one plate's prompt from *its own segment* of the page (causality-safe: the
        segment is a sub-range of that page's text). For a single-image page the segment is the
        whole page, so this is identical to the pre-feature per-page derivation."""
        plates = _selected_plates(cfg, job)
        rec = next((r for r in plates if r["plate_id"] == plate_id), None)
        if rec is None:  # pragma: no cover - units() only emits selected plate ids
            return
        page = _read_json(_pages_dir(cfg, job) / f"{rec['page_id']}.json")
        n_segments = _segments_per_page(plates)[rec["page_id"]]
        segment = even_segments(page["text"], n_segments)[rec["segment_index"]]
        options = illustration_options(page, _load_cast(cfg, job), job.bake_config.get("era"))
        output, meta = await TtsClient(cfg).transform_with_meta(TRANSFORM, segment.text, options)

        warnings = meta.get("warnings") or []
        if warnings:
            job.prompt_warnings[plate_id] = list(warnings)

        doc = _draft(plate_id, output["prompt"], derived=output)
        schemas.validate("prompt", doc)
        _write_json(_prompts_dir(cfg, job) / f"{plate_id}.json", doc)

    # --- CPU pseudo-plates (DESIGN §10) ------------------------------------

    def _write_cover(self, cfg: Any, job: Job) -> None:
        style = resolve_style(job.bake_config)
        prompt = assemble_cover(style, _title(job), _author(job), cover_beat(_load_pages(cfg, job)))
        doc = _draft(COVER_UNIT_ID, prompt)
        schemas.validate("prompt", doc)
        _write_json(_prompts_dir(cfg, job) / f"{COVER_UNIT_ID}.json", doc)

    def _write_portrait(self, cfg: Any, job: Job, unit_id: str) -> None:
        slug = unit_id[len(PORTRAIT_PREFIX):]
        char = next(
            (c for c in _load_cast(cfg, job).get("characters", []) if c.get("slug") == slug),
            None,
        )
        if char is None:  # pragma: no cover - units() only emits ids that exist in the cast
            return
        style = resolve_style(job.bake_config)
        prompt = assemble_portrait(style, char["one_line"], char["visual_description"])
        doc = _draft(unit_id, prompt)
        schemas.validate("prompt", doc)
        _write_json(_prompts_dir(cfg, job) / f"{unit_id}.json", doc)
