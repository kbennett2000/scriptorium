"""P5 pure assembly helpers — cast filtering/capping + CPU pseudo-plate strings (DESIGN §10).

No runner, no TTS: these test the deterministic string/option assembly directly. Per CLAUDE.md
the pseudo-plate prompts are CPU-assembled (no LLM), so — unlike per-page prompts — their exact
strings *are* asserted, against the §10 formulas.
"""

from __future__ import annotations

import re

import pytest

from scriptorium.bake.phases.p5_prompts import (
    CAST_CAP,
    PORTRAIT_SOLO,
    assemble_cover,
    assemble_portrait,
    condense,
    cover_beat,
    eligible_portraits,
    illustration_options,
    present_cast,
    subject_attributes,
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
    # {name, one_line} always; a described character (ADR-0032) also carries condensed appearance.
    assert all({"name", "one_line"} <= set(c) <= {"name", "one_line", "appearance"} for c in out)
    assert all(c["appearance"] == "desc" for c in out)


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
    assert opts["cast"] == [{"name": "A", "one_line": "a", "appearance": "desc"}]
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
    # ADR-0028: solo framing, the subject named once (one_line, its full stop dropped so the
    # attributes read as a continuation), then the description as attribute clauses.
    assert got == (
        f"{_ENGRAVING['portrait_prefix']}{PORTRAIT_SOLO}"
        "The keeper of the workshop at the end of the lane, "
        + vd
    )


# --- ADR-0028: the portrait prompt names its subject exactly once -----------

# Real (one_line, visual_description) pairs from the published pg-28054 bake, whose portraits fed
# IP-Adapter for 348 plates. 25 of that book's 69 portrait prompts named the subject 2-3 times;
# `mitya` is the one that mattered — its portrait rendered as two officers and anchored 84 plates.
_REAL_CAST = [
    ("Young man in stained officer's uniform with bloody face and hands",
     "A young Russian gentleman with a blood-stained face and trembling fingers, dressed in an "
     "officer's uniform that appears rumpled from running like a madman."),
    ("Feeble old monk with pale lips and downcast eyes",
     "A feeble old man with pale, bloodless lips and frightened little eyes sits unmoved with "
     "downcast gaze. He wears a hat held in his hand as he sways while walking."),
    ("Frenzied twenty-seven-year-old man in feverish agitation",
     "A twenty-seven-year-old man with a frenzied face and feverish agitation stands mounted on "
     "something, his powerful hand gripping tightly as he leaps up."),
    ("Golden-haired young man of twenty-eight, medium height, thin build with hollow cheeks",
     "A young man of eight and twenty with golden hair stands at medium height, appearing rather "
     "thin. He is muscular yet shows signs of considerable physical strength."),
    ("Plump Russian woman in black silk dress, lace fichu, and gold-brooch shawl",
     "A plump, rosy beauty of the Russian type with a full figure and slim, delicate limbs. She "
     "wears a black silk dress with a dainty lace fichu on her head."),
    ("Old man with bashful expression and melting voice",
     "An old man with a bashful expression and melting voice stands before Captain Snegiryov's "
     "lodging, his eyes full of pity."),
    ("Tall vigorous old monk in red coarse coat with rope waist, grey eyes",
     "A tall, vigorous old man with an athletic build stands erect and carries himself well."),
    ("Stout Russian servant in simple dress, marked by smallpox",
     "A stout woman of forty with a full figure and small-pox marks on her face."),
    ("Man of unspecified age with a plain era-appropriate build",
     "A man of unspecified apparent age with a plain, era-appropriate build stands in the setting "
     "of Russia during the 1870s."),
]

# A determiner + optional modifiers + person noun: an *independent* subject. One is the subject
# itself; a second one is the defect this ADR exists to stop.
_SUBJECT_PHRASE = re.compile(
    r"\b(?:a|an|the)\s+(?:[\w'-]+,?\s+){0,5}?"
    r"(?:man|woman|boy|girl|gentleman|lady|monk|priest|peasant|youth|beauty|servant)s?\b",
    re.I,
)


@pytest.mark.parametrize(("one_line", "vd"), _REAL_CAST)
def test_portrait_prompt_never_names_a_second_subject(one_line: str, vd: str) -> None:
    got = assemble_portrait(_ENGRAVING, one_line, vd)
    attributes = got.split(one_line.rstrip(" ."), 1)[1]
    assert not _SUBJECT_PHRASE.search(attributes), (
        f"description still opens a second subject: {attributes!r}"
    )


@pytest.mark.parametrize(("one_line", "vd"), _REAL_CAST)
def test_portrait_prompt_states_solo_framing_and_names_subject_once(one_line: str, vd: str) -> None:
    got = assemble_portrait(_ENGRAVING, one_line, vd)
    assert PORTRAIT_SOLO in got
    assert got.count(one_line.rstrip(" .")) == 1


def test_subject_attributes_drops_posture_and_setting() -> None:
    got = subject_attributes(
        "A man of unspecified apparent age with a plain build stands in the setting of Russia."
    )
    assert "stands" not in got
    assert "Russia" not in got
    assert "plain build" in got


def test_subject_attributes_folds_a_pronoun_clause_into_an_attribute() -> None:
    got = subject_attributes("A stout woman of forty. She wears a black silk dress.")
    assert got.startswith("of forty")
    assert "wearing a black silk dress" in got
    assert "She wears" not in got


def test_subject_attributes_leaves_an_unrecognised_opening_alone() -> None:
    # No leading person noun => nothing is stripped (pre-ADR-0028 behaviour, never silently wrong).
    text = "weathered hands and a squint earned at sea"
    assert subject_attributes(text) == text


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
