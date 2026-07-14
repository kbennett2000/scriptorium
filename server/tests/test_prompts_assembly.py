"""P5 pure assembly helpers — cast filtering/capping + CPU pseudo-plate strings (DESIGN §10).

No runner, no TTS: these test the deterministic string/option assembly directly. Per CLAUDE.md
the pseudo-plate prompts are CPU-assembled (no LLM), so — unlike per-page prompts — their exact
strings *are* asserted, against the §10 formulas.
"""

from __future__ import annotations

from scriptorium.bake.phases.p5_prompts import (
    CAST_CAP,
    assemble_cover,
    assemble_portrait,
    condense,
    cover_beat,
    eligible_portraits,
    illustration_options,
    present_cast,
)
from scriptorium.styles import get_style

_ENGRAVING = get_style("engraving")


def _char(slug, name, *, aliases=None, mention_pages=None, one_line="", major=True, vd="desc"):
    return {
        "slug": slug, "name": name, "aliases": aliases or [],
        "mention_pages": mention_pages or [], "major": major,
        "visual_description": vd, "one_line": one_line, "tags": [],
        "portrait": None, "edited_by_human": False,
    }


# --- present-cast filter + cap (TTS §7.5) -----------------------------------


def test_present_cast_matches_name_or_alias() -> None:
    cast = {"characters": [
        _char("a", "the Clockmaker", aliases=["the old clockmaker"], one_line="A"),
        _char("b", "the Stranger", one_line="B"),
        _char("c", "Weena", one_line="C"),
    ]}
    # 'the old clockmaker' matches by alias; 'the Stranger' by name; Weena is absent.
    ledger = {"present": ["the old clockmaker", "the Stranger"]}
    out = present_cast(cast, ledger)
    assert {c["name"] for c in out} == {"the Clockmaker", "the Stranger"}
    assert all(set(c) == {"name", "one_line"} for c in out)  # exactly {name, one_line}


def test_present_cast_empty_present_is_empty() -> None:
    cast = {"characters": [_char("a", "X", one_line="A")]}
    assert present_cast(cast, {"present": []}) == []
    assert present_cast(cast, {}) == []


def test_present_cast_caps_at_four_by_mention_frequency() -> None:
    # Five present characters with descending mention counts; only the top 4 survive.
    cast = {"characters": [
        _char("a", "A", mention_pages=["0001"], one_line="a"),
        _char("b", "B", mention_pages=["0001", "0002", "0003", "0004", "0005"], one_line="b"),
        _char("c", "C", mention_pages=["0001", "0002"], one_line="c"),
        _char("d", "D", mention_pages=["0001", "0002", "0003", "0004"], one_line="d"),
        _char("e", "E", mention_pages=["0001", "0002", "0003"], one_line="e"),
    ]}
    ledger = {"present": ["A", "B", "C", "D", "E"]}
    out = present_cast(cast, ledger)
    assert len(out) == CAST_CAP
    # Ordered by frequency desc: B(5) D(4) E(3) C(2); A(1) is dropped.
    assert [c["name"] for c in out] == ["B", "D", "E", "C"]


def test_present_cast_tiebreak_prefers_earlier_first_mention() -> None:
    # Equal mention counts → earliest first-mention page wins the ordering.
    cast = {"characters": [
        _char("a", "A", mention_pages=["0005", "0006"], one_line="a"),
        _char("b", "B", mention_pages=["0002", "0009"], one_line="b"),
    ]}
    out = present_cast(cast, {"present": ["A", "B"]})
    assert [c["name"] for c in out] == ["B", "A"]  # B first-mentioned on 0002


def test_illustration_options_shape() -> None:
    cast = {"characters": [_char("a", "A", mention_pages=["0001"], one_line="a")]}
    page = {"ledger": {"present": ["A"], "location": "x"}}
    opts = illustration_options(page, cast, era="an imagined coast")
    assert opts["ledger"] == page["ledger"]  # full ledger passed through
    assert opts["cast"] == [{"name": "A", "one_line": "a"}]
    assert opts["era"] == "an imagined coast"
    # era omitted when falsy (TTS options.era is optional).
    assert "era" not in illustration_options(page, cast, era=None)


# --- cover pseudo-plate (DESIGN §10) ----------------------------------------


def test_cover_beat_picks_max_salience_chapter_one_page() -> None:
    pages = [
        {"id": "0001", "seq": 1, "chapter": 1,
         "ledger": {"visual_salience": 0.5, "best_visual_beat": "low"}},
        {"id": "0002", "seq": 2, "chapter": 1,
         "ledger": {"visual_salience": 0.9, "best_visual_beat": "the winning beat"}},
        {"id": "0003", "seq": 3, "chapter": 2,
         "ledger": {"visual_salience": 0.99, "best_visual_beat": "chapter two, ignored"}},
    ]
    assert cover_beat(pages) == "the winning beat"


def test_cover_beat_tiebreak_earliest_seq() -> None:
    pages = [
        {"id": "0002", "seq": 2, "chapter": 1,
         "ledger": {"visual_salience": 0.8, "best_visual_beat": "later"}},
        {"id": "0001", "seq": 1, "chapter": 1,
         "ledger": {"visual_salience": 0.8, "best_visual_beat": "earlier"}},
    ]
    assert cover_beat(pages) == "earlier"


def test_assemble_cover_matches_design_formula() -> None:
    beat = "a silvered harbour under a cold sun"
    got = assemble_cover(_ENGRAVING, "The Tidewatch Fragment", "A. Fixture", beat)
    expected = (
        _ENGRAVING["prefix"]
        + "frontispiece for the book 'The Tidewatch Fragment' by A. Fixture: "
        + beat
        + _ENGRAVING["suffix"]
    )
    assert got == expected


# --- portrait pseudo-plates (DESIGN §10) ------------------------------------


def test_assemble_portrait_matches_design_formula() -> None:
    one_line = "The keeper of the workshop at the end of the lane."
    vd = "a spare, white-haired artisan in a leather apron, hands stained with brass polish"
    got = assemble_portrait(_ENGRAVING, one_line, vd)
    assert got == f"{_ENGRAVING['portrait_prefix']}{one_line}, {vd}"


def test_condense_passes_short_text_through() -> None:
    short = "a spare, white-haired artisan in a leather apron"
    assert condense(short, max_words=60) == short


def test_condense_truncates_on_sentence_boundary() -> None:
    # 12 short sentences of ~6 words each (> 60 words); condensing cuts on a sentence boundary.
    long = " ".join(f"Sentence number {i} runs on here." for i in range(1, 13))
    out = condense(long, max_words=60)
    assert len(out.split()) <= 60
    assert out.endswith(".")  # cut fell on a sentence boundary, not mid-word
    assert long.startswith(out)  # a prefix of the original


def test_condense_hard_truncates_when_no_sentence_boundary() -> None:
    long = " ".join(["word"] * 100)  # no punctuation at all
    out = condense(long, max_words=60)
    assert out.split() == ["word"] * 60


def test_eligible_portraits_only_majors_with_description() -> None:
    cast = {"characters": [
        _char("a", "Major With Desc", major=True, vd="a tall figure"),
        _char("b", "Major No Desc", major=True, vd=None),
        _char("c", "Minor", major=False, vd=None),
    ]}
    out = eligible_portraits(cast)
    assert [c["slug"] for c in out] == ["a"]
