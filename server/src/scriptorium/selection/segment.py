"""Even paragraph-segmentation for the "pictures per scene" feature (DESIGN §8).

A selected page can carry more than one illustration, woven evenly through its text. This module
splits a page's canonical ``text`` into ``n`` contiguous, evenly-sized paragraph groups — one per
illustration — and reports each group's text plus the **UTF-16 code-unit** offset of its first
paragraph. That offset is the plate's ``anchor``: the reader resolves it through the exact same
paragraph math (``pagetext.ts`` ``splitParagraphs``/``paragraphStarts``), so a picture lands
between the right paragraphs without touching the byte-faithful text.

Determinism + causality: pure function of the page text (no randomness); every segment's text is a
sub-range of that one page (≤ page N), so it never reads ahead. Used by P4 (to place plates +
anchors) and P5 (to derive each plate's prompt from its own segment) — kept in one place so the two
never drift.
"""

from __future__ import annotations

from dataclasses import dataclass

from .engine import PlateChoice

_PARA_SEP = "\n\n"
_SEGMENT_REASON = "segment"


@dataclass(frozen=True)
class Segment:
    """One evenly-spaced slice of a page: its index, its text, and its anchor offset."""

    index: int
    anchor: int  # UTF-16 code-unit offset of the segment's first paragraph within the page text
    text: str  # the segment's paragraphs, rejoined with the canonical "\n\n" separator


def _utf16_len(s: str) -> int:
    """Length of ``s`` in UTF-16 code units (matches JS ``String.length`` reader-side)."""
    return len(s.encode("utf-16-le")) // 2


def _paragraph_starts(paragraphs: list[str]) -> list[int]:
    """UTF-16 start offset of each paragraph — the inverse of the reader's ``paragraphStarts``.

    ``starts[i] = Σ_{j<i} utf16len(paragraphs[j]) + 2·i`` (the ``\\n\\n`` join is 2 code units).
    """
    starts: list[int] = []
    offset = 0
    for para in paragraphs:
        starts.append(offset)
        offset += _utf16_len(para) + 2  # +2 for the "\n\n" join
    return starts


def even_segments(page_text: str, n: int) -> list[Segment]:
    """Split ``page_text`` into ``min(n, paragraph_count)`` even, contiguous paragraph groups.

    ``n`` is the requested pictures-per-scene (≥1). A scene holds at most as many pictures as it has
    paragraphs, so a single-paragraph page always yields exactly one segment regardless of ``n``.
    Segment ``k`` covers paragraphs ``[k·P // count, (k+1)·P // count)`` — an even partition; its
    ``anchor`` is that group's first-paragraph offset (segment 0 is always anchor 0 / top).
    """
    paragraphs = page_text.split(_PARA_SEP)
    starts = _paragraph_starts(paragraphs)
    total = len(paragraphs)
    count = max(1, min(n, total))
    bounds = [(k * total) // count for k in range(count)] + [total]
    return [
        Segment(
            index=k,
            anchor=starts[bounds[k]],
            text=_PARA_SEP.join(paragraphs[bounds[k] : bounds[k + 1]]),
        )
        for k in range(count)
    ]


def expand_choices(
    choices: list[PlateChoice], page_texts: dict[str, str], images_per_scene: int
) -> list[PlateChoice]:
    """Turn one-per-page selection choices into up to ``images_per_scene`` plates per page.

    Each selected page is split into even segments (:func:`even_segments`): the first stays a bare
    page plate (unchanged from single-image bakes), and each extra becomes a compound-id choice
    carrying its ``anchor`` and ``segment_index``. Preserves ``choices`` order. Used by P4 (fresh
    bake) and re-selection so the two produce identical plate shapes.
    """
    expanded: list[PlateChoice] = []
    for choice in choices:
        for seg in even_segments(page_texts.get(choice.page_id, ""), images_per_scene):
            if seg.index == 0:
                expanded.append(
                    PlateChoice(choice.page_id, choice.reason, choice.salience)
                )
            else:
                expanded.append(
                    PlateChoice(
                        choice.page_id,
                        _SEGMENT_REASON,
                        choice.salience,
                        plate_id=f"{choice.page_id}-{seg.index + 1}",
                        anchor=seg.anchor,
                        segment_index=seg.index,
                    )
                )
    return expanded
