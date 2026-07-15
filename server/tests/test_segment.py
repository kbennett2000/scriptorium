"""Even paragraph-segmentation (selection/segment.py) for pictures-per-scene.

Pure, deterministic; asserts structure/offsets only. The UTF-16 anchor math must mirror the
reader's pagetext.ts (paragraphs joined by "\n\n", offsets in UTF-16 code units).
"""

from __future__ import annotations

from scriptorium.selection.segment import even_segments

_THREE = "Para one.\n\nPara two.\n\nPara three."


def test_n1_is_the_whole_page_at_top() -> None:
    segs = even_segments(_THREE, 1)
    assert len(segs) == 1
    assert segs[0].index == 0
    assert segs[0].anchor == 0
    assert segs[0].text == _THREE


def test_splits_evenly_with_top_anchors_at_paragraph_starts() -> None:
    segs = even_segments(_THREE, 3)
    assert [s.index for s in segs] == [0, 1, 2]
    assert [s.text for s in segs] == ["Para one.", "Para two.", "Para three."]
    # UTF-16 offsets: "Para one." = 9 + 2 ("\n\n") = 11; "Para two." = 9 + 2 = 11 -> 22.
    assert [s.anchor for s in segs] == [0, 11, 22]


def test_caps_at_paragraph_count() -> None:
    # One paragraph can hold only one picture regardless of the requested count.
    segs = even_segments("Only one paragraph here.", 5)
    assert len(segs) == 1
    assert segs[0].anchor == 0


def test_more_paragraphs_than_pictures_groups_contiguously() -> None:
    text = "\n\n".join(f"P{i}" for i in range(6))  # 6 paragraphs
    segs = even_segments(text, 2)
    assert len(segs) == 2
    assert segs[0].text == "P0\n\nP1\n\nP2"
    assert segs[1].text == "P3\n\nP4\n\nP5"
    assert segs[0].anchor == 0


def test_astral_char_counts_as_two_utf16_units() -> None:
    # An emoji (astral) is 2 UTF-16 code units — the anchor must reflect that (reader parity).
    text = "a\U0001F600b\n\nsecond"  # first para: a + emoji(2) + b = 4 UTF-16 units
    segs = even_segments(text, 2)
    assert segs[1].anchor == 4 + 2  # first-para length (4) + "\n\n" (2)
