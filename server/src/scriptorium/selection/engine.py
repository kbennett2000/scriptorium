"""P4 selection engine — the deterministic plate-selection function (DESIGN §8).

``select(scores, structure, params)`` is a **pure, deterministic** function: the same scores
and params always yield byte-identical output. No randomness, and every tie-break is fully
specified, so annotation-free re-selection stays reproducible.

**Spoiler invariant, made structural.** The input :class:`PageScore` carries *numbers and
booleans only* — ``seq``, ``page_id`` (an identifier, not content), ``chapter``,
``scene_changed``, ``visual_salience``. No text field can enter selection, so the engine
cannot "read ahead" into page content; score lookahead is allowed, content lookahead is not
(DESIGN §8). A test asserts the field set exactly.

The five §8 steps are implemented in :func:`select`:

1. **Mandatory marks** — the first page of each chapter (``chapter_open``) and, when the preset
   enables it, every ``scene_changed`` page (``scene_boundary``).
2. **Enforce ``min_gap``** over marks in seq order: two marks closer than ``min_gap`` collapse to
   the higher-precedence one (``chapter_open`` > ``scene_boundary``), tie-broken by higher
   salience then earlier seq.
3. **Fill** the gaps: wherever the run since the last kept plate would exceed ``max_gap``, take
   the highest-salience page clearing ``salience_floor`` in the window; if none clears the floor,
   leave the gap (a gap may exceed ``max_gap`` rather than force a weak plate).
4. **Tiny-work** degradation: a book under 8 pages collapses to ``{page 1} ∪ {argmax salience}``.
5. Emit a ``reason`` per plate.

**Fill window vs. ``min_gap`` (deliberate reconciliation).** §8 step 3 writes the fill window as
``(last+1 … last+max_gap)``, but the binding acceptance property is "no two plates closer than
``min_gap``" over *all* plates — including fills. A literal ``last+1`` lower bound can seat a fill
one page from an anchor and break that property. This engine therefore intersects the fill window
with the ``min_gap`` constraint: ``[last+min_gap, min(last+max_gap, next_anchor−min_gap)]``. For
all three presets ``max_gap ≥ 2·min_gap``, so a fill region is always wide enough for a valid
slot; the floor is the only reason a gap is left unfilled.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

# --- public types ----------------------------------------------------------

CHAPTER_OPEN = "chapter_open"
SCENE_BOUNDARY = "scene_boundary"
FILL = "fill"
MANUAL = "manual"

# Below this page count the presets are ignored (DESIGN §8 step 4).
TINY_WORK_THRESHOLD = 8

# Mandatory-mark precedence: lower rank wins a min_gap collision (DESIGN §8 step 2).
_PRECEDENCE = {CHAPTER_OPEN: 0, SCENE_BOUNDARY: 1}


@dataclass(frozen=True)
class PageScore:
    """The spoiler-safe selection input for one page: numbers and booleans only.

    ``page_id`` is a zero-padded identifier, never page content. Adding any text field here
    would breach the spoiler invariant — a test pins the field set.
    """

    seq: int
    page_id: str
    chapter: int
    scene_changed: bool
    visual_salience: float


@dataclass(frozen=True)
class Params:
    """Effective selection parameters (one row of the §8 preset table)."""

    min_gap: int
    max_gap: int
    salience_floor: float
    chapter_open: bool
    scene_boundary: bool

    def as_dict(self) -> dict:
        """The ``params`` object as it is written into ``selection.json``."""
        return {
            "min_gap": self.min_gap,
            "max_gap": self.max_gap,
            "salience_floor": self.salience_floor,
            "chapter_open": self.chapter_open,
            "scene_boundary": self.scene_boundary,
        }


@dataclass(frozen=True)
class PlateChoice:
    """One selected plate: which page, why, and its salience at selection time.

    ``status`` and ``added_in_revision`` are attached at serialization (a fresh selection is
    ``selected`` / revision 1) or by :mod:`scriptorium.selection.reselect`.
    """

    page_id: str
    reason: str
    salience: float


# The §8 preset table, verbatim (min_gap, max_gap, salience_floor, chapter_open, scene_boundary).
PRESETS: dict[str, Params] = {
    "lavish": Params(1, 3, 0.40, True, True),
    "classic": Params(2, 6, 0.55, True, True),
    "sparse": Params(4, 12, 0.85, True, False),
}


# --- internal ---------------------------------------------------------------


@dataclass(frozen=True)
class _Mark:
    """A page kept as a mandatory mark, with the reason it qualified."""

    score: PageScore
    reason: str


def select(scores: list[PageScore], structure: dict, params: Params) -> list[PlateChoice]:
    """Choose plates for ``scores`` under ``params`` (DESIGN §8). Deterministic."""
    if not scores:
        return []
    ordered = sorted(scores, key=lambda s: s.seq)

    # Step 4: tiny-work degradation ignores the presets entirely.
    if len(ordered) < TINY_WORK_THRESHOLD:
        return _tiny_work(ordered)

    # Step 1: mandatory marks in seq order.
    opener_ids = _chapter_opener_ids(structure) if params.chapter_open else set()
    marks = _mandatory_marks(ordered, opener_ids, params)

    # Step 2: collapse marks closer than min_gap by precedence/salience/seq.
    kept = _enforce_min_gap(marks, params.min_gap)

    # Step 3: fill gaps wider than max_gap where salience permits.
    plates = _fill(ordered, kept, params)

    # Step 5: emit reasons, in seq order.
    plates.sort(key=lambda m: m.score.seq)
    return [PlateChoice(m.score.page_id, m.reason, m.score.visual_salience) for m in plates]


def _tiny_work(ordered: list[PageScore]) -> list[PlateChoice]:
    """{page 1} ∪ {argmax salience}, deduped (DESIGN §8 step 4)."""
    first = ordered[0]
    # argmax salience, earliest seq on a tie (deterministic).
    argmax = max(ordered, key=lambda s: (s.visual_salience, -s.seq))
    plates = [PlateChoice(first.page_id, CHAPTER_OPEN, first.visual_salience)]
    if argmax.seq != first.seq:
        reason = SCENE_BOUNDARY if argmax.scene_changed else FILL
        plates.append(PlateChoice(argmax.page_id, reason, argmax.visual_salience))
    return plates


def _chapter_opener_ids(structure: dict) -> set[str]:
    """The first page id of each chapter (DESIGN §8 step 1 chapter_open)."""
    ids: set[str] = set()
    for chapter in structure.get("chapters", []):
        page_ids = chapter.get("page_ids") or []
        if page_ids:
            ids.add(page_ids[0])
    return ids


def _mandatory_marks(
    ordered: list[PageScore], opener_ids: set[str], params: Params
) -> list[_Mark]:
    """Chapter openers and (if enabled) scene boundaries, in seq order.

    A page that is both a chapter opener and a scene boundary is a ``chapter_open`` mark
    (higher precedence).
    """
    marks: list[_Mark] = []
    for score in ordered:
        if score.page_id in opener_ids:
            marks.append(_Mark(score, CHAPTER_OPEN))
        elif params.scene_boundary and score.scene_changed:
            marks.append(_Mark(score, SCENE_BOUNDARY))
    return marks


def _rank(mark: _Mark) -> tuple[int, float, int]:
    """Sort key where *lower is better*: precedence, then higher salience, then earlier seq."""
    return (_PRECEDENCE[mark.reason], -mark.score.visual_salience, mark.score.seq)


def _enforce_min_gap(marks: list[_Mark], min_gap: int) -> list[_Mark]:
    """Collapse marks closer than ``min_gap`` (DESIGN §8 step 2), greedily in seq order.

    A later mark that beats the kept tail pops it and re-checks the new tail, so a run of
    too-close marks resolves to a single deterministic winner.
    """
    kept: list[_Mark] = []
    for mark in marks:
        current: _Mark | None = mark
        while kept and (current.score.seq - kept[-1].score.seq) < min_gap:
            if _rank(kept[-1]) <= _rank(current):
                current = None  # the kept tail wins; drop the newcomer
                break
            kept.pop()  # the newcomer wins; drop the tail and re-check
        if current is not None:
            kept.append(current)
    return kept


def _fill(ordered: list[PageScore], kept: list[_Mark], params: Params) -> list[_Mark]:
    """Add ``fill`` plates so no gap exceeds ``max_gap`` where salience permits (§8 step 3)."""
    by_seq = {s.seq: s for s in ordered}
    min_seq, max_seq = ordered[0].seq, ordered[-1].seq
    kept_sorted = sorted(kept, key=lambda m: m.score.seq)
    taken = {m.score.seq for m in kept_sorted}
    result = list(kept_sorted)
    anchors = [m.score.seq for m in kept_sorted]

    if not anchors:
        # No mandatory marks at all: fill the whole book from a virtual anchor at its start.
        result.extend(
            _fill_region(min_seq - 1, None, by_seq, taken, params, max_seq)
        )
        return result

    # Head (book start → first anchor), interior (anchor → anchor), tail (last anchor → end).
    result.extend(_fill_region(min_seq - 1, anchors[0], by_seq, taken, params, max_seq))
    for left, right in zip(anchors, anchors[1:], strict=False):
        result.extend(_fill_region(left, right, by_seq, taken, params, max_seq))
    result.extend(_fill_region(anchors[-1], None, by_seq, taken, params, max_seq))
    return result


def _fill_region(
    last: int,
    right: int | None,
    by_seq: dict[int, PageScore],
    taken: set[int],
    params: Params,
    max_seq: int,
) -> list[_Mark]:
    """Greedily fill one region ``(last, right)``.

    ``right`` is a real closing anchor seq, or ``None`` for the tail (fill up to the book end).
    The window is intersected with ``min_gap`` on both sides so the global "no two plates closer
    than min_gap" property holds (see module docstring).
    """
    fills: list[_Mark] = []
    while True:
        if right is not None:
            if right - last <= params.max_gap:
                break
            win_hi = min(last + params.max_gap, right - params.min_gap)
        else:
            if max_seq - last <= params.max_gap:
                break
            win_hi = min(last + params.max_gap, max_seq)
        win_lo = last + params.min_gap
        candidate = _argmax_salience(by_seq, win_lo, win_hi, params.salience_floor, taken)
        if candidate is None:
            # Nothing clears the floor here: leave the gap and advance the cursor (§8 step 3).
            last += params.max_gap
            continue
        fills.append(_Mark(candidate, FILL))
        taken.add(candidate.seq)
        last = candidate.seq
    return fills


def _argmax_salience(
    by_seq: dict[int, PageScore], lo: int, hi: int, floor: float, taken: set[int]
) -> PageScore | None:
    """Highest-salience page in ``[lo, hi]`` clearing ``floor`` and not taken; earliest on tie."""
    best: PageScore | None = None
    for seq in range(lo, hi + 1):
        score = by_seq.get(seq)
        if score is None or seq in taken or score.visual_salience < floor:
            continue
        # Ascending scan + strict '>' makes the earliest seq win a salience tie.
        if best is None or score.visual_salience > best.visual_salience:
            best = score
    return best


def page_score_fields() -> tuple[str, ...]:
    """The field names of :class:`PageScore` (used by the spoiler-invariant test)."""
    return tuple(f.name for f in fields(PageScore))
