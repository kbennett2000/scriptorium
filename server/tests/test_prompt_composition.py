"""Prompt composition + depicted→cast resolution (ADR-0026).

Pure-function coverage for the three things that decide what a plate actually looks like: the
period anchor and shot framing baked into ``wrap_prompt``, the hardened negative, and — the
headline fix — which character's portrait is allowed to condition a page plate.

Image *content* is never asserted (CLAUDE.md); these check the strings and the reference choice.
"""

from __future__ import annotations

from scriptorium.bake.phases.p7_render import (
    build_cast_index,
    portrait_reference,
    reference_conditioning,
    resolve_character,
    wrap_prompt,
)
from scriptorium.styles import get_style

# A cast shaped like the real Karamazov one: majors with portraits, a minor without, and a name
# the transform is prone to over-qualifying ("Pyotr Ilyitch" → "Pyotr Ilyitch Karamazov").
CAST = [
    {"slug": "pyotr-ilyitch", "name": "Pyotr Ilyitch", "aliases": ["Perhotin"]},
    {"slug": "hohlakov", "name": "Hohlakov", "aliases": ["Katerina Osipovna"]},
    {"slug": "nastasya", "name": "Nastasya", "aliases": []},
    {"slug": "zossima", "name": "Zossima", "aliases": ["the elder"]},
]


def _doc(prompt: str, *, depicted=None, shot=None, avoid=None) -> dict:
    derived: dict = {"prompt": prompt}
    if depicted is not None:
        derived["depicted"] = depicted
    if shot is not None:
        derived["shot"] = shot
    if avoid is not None:
        derived["avoid"] = avoid
    return {"page_id": "0001", "derived": derived,
            "edited_prompt": None, "final_subject_prompt": prompt}


# --- depicted → cast resolution ---------------------------------------------


def test_resolves_exact_name_and_alias() -> None:
    idx = build_cast_index(CAST)
    assert resolve_character("Pyotr Ilyitch", idx) == "pyotr-ilyitch"
    assert resolve_character("perhotin", idx) == "pyotr-ilyitch"


def test_resolves_through_articles_and_honorifics() -> None:
    idx = build_cast_index(CAST)
    assert resolve_character("The Elder", idx) == "zossima"
    assert resolve_character("Madame Hohlakov", idx) == "hohlakov"
    assert resolve_character("Father Zossima", idx) == "zossima"


def test_resolves_an_over_qualified_name() -> None:
    # The transform invents compound surnames; before ADR-0026 this simply failed to match and the
    # plate silently took the *next* depicted character's face.
    idx = build_cast_index(CAST)
    assert resolve_character("Pyotr Ilyitch Karamazov", idx) == "pyotr-ilyitch"


def test_ambiguous_and_unknown_labels_resolve_to_nothing() -> None:
    # An alias claimed by two characters is a cast-reduction defect (ADR-0019/0022) — refuse it
    # rather than guessing a face.
    idx = build_cast_index([
        {"slug": "a", "name": "Alpha", "aliases": ["the elder"]},
        {"slug": "b", "name": "Beta", "aliases": ["the elder"]},
    ])
    assert resolve_character("the elder", idx) is None
    assert resolve_character("Someone Entirely Else", idx) is None
    assert resolve_character("", idx) is None


# --- which portrait may condition a plate ------------------------------------


def _portraits(tmp_path, *slugs):
    d = tmp_path / "portraits"
    d.mkdir(parents=True, exist_ok=True)
    for s in slugs:
        (d / f"{s}.png").write_bytes(b"PNG:" + s.encode())
    return d


def test_primary_character_with_a_portrait_conditions_the_plate(tmp_path) -> None:
    d = _portraits(tmp_path, "pyotr-ilyitch", "hohlakov")
    refs, slug = portrait_reference(["Pyotr Ilyitch", "Hohlakov"], CAST, d)
    assert slug == "pyotr-ilyitch"
    assert refs == [b"PNG:pyotr-ilyitch"]


def test_minor_primary_never_falls_through_to_a_secondary(tmp_path) -> None:
    # Plate 0033: depicted = [Nastasya (a minor, no portrait), the elder]. The old first-match loop
    # fell through and conditioned the whole plate on the elder's portrait — which is why "a woman
    # kneels before the elder" rendered as two monks and no woman.
    d = _portraits(tmp_path, "zossima")
    refs, slug = portrait_reference(["Nastasya", "the elder"], CAST, d)
    assert refs is None and slug is None


def test_unresolvable_primary_never_falls_through_to_a_secondary(tmp_path) -> None:
    # Plate 0345: the transform wrote "Pyotr Ilyitch Karamazov"; with no portrait for him the plate
    # must render prompt-only rather than borrowing Madame Hohlakov's face (which drew two women).
    d = _portraits(tmp_path, "hohlakov")
    refs, slug = portrait_reference(["Pyotr Ilyitch Karamazov", "Madame Hohlakov"], CAST, d)
    assert refs is None and slug is None


def test_no_depicted_characters_means_no_reference(tmp_path) -> None:
    assert portrait_reference([], CAST, _portraits(tmp_path, "zossima")) == (None, None)


# --- wrap_prompt: era, shot, negative ----------------------------------------


def test_era_anchors_the_page_prompt() -> None:
    style = get_style("engraving")
    wrapped, _ = wrap_prompt(style, "0001", _doc("a monk in a red coarse coat"), "Russia 1870s")
    assert "Russia 1870s, a monk in a red coarse coat" in wrapped
    assert wrapped.startswith(style["prefix"])
    assert wrapped.endswith(style["suffix"])


def test_absent_or_blank_era_leaves_the_prompt_clean() -> None:
    style = get_style("engraving")
    for era in (None, "", "   "):
        wrapped, _ = wrap_prompt(style, "0001", _doc("a quiet room"), era)
        assert wrapped == f"{style['prefix']}a quiet room{style['suffix']}"


def test_shot_becomes_composition_language() -> None:
    style = get_style("engraving")
    for shot, expect in [("close", "close-up"), ("medium", "medium shot"),
                         ("wide", "wide establishing shot")]:
        wrapped, _ = wrap_prompt(style, "0001", _doc("a figure", shot=shot))
        assert expect in wrapped
    # An unknown/missing shot contributes nothing rather than a stray comma.
    wrapped, _ = wrap_prompt(style, "0001", _doc("a figure", shot="dutch-angle"))
    assert wrapped == f"{style['prefix']}a figure{style['suffix']}"


def test_subject_full_stop_is_dropped_before_the_style_suffix() -> None:
    style = get_style("engraving")
    wrapped, _ = wrap_prompt(style, "0001", _doc("he realised it was too late."))
    assert "too late," in wrapped
    assert "late.," not in wrapped


def test_negative_gains_the_global_guards_without_duplicates() -> None:
    # oil-painting already carried anti-anachronism terms ad hoc; the global tail must not repeat
    # them, and must add the duplication/anatomy guards no style had.
    style = get_style("oil-painting")
    _, negative = wrap_prompt(style, "0001", _doc("a scene", avoid=["fog"]))
    terms = [t.strip() for t in negative.split(",")]
    assert "duplicate" in terms and "cloned face" in terms and "bad anatomy" in terms
    assert "fog" in terms  # derived.avoid still applied
    assert len(terms) == len(set(terms)), f"duplicate negative terms: {negative}"


# --- ADR-0036: the owner's book-wide negative is appended, not substituted ---


def test_user_negative_is_appended_after_the_derived_guards() -> None:
    style = get_style("engraving")
    _, negative = wrap_prompt(
        style, "0001", _doc("a scene", avoid=["fog"]), user_negative="text, watermark"
    )
    terms = [t.strip() for t in negative.split(",")]
    # The safety net and derived avoids survive...
    assert "duplicate" in terms and "bad anatomy" in terms and "fog" in terms
    # ...and the owner's terms are layered on top.
    assert "text" in terms and "watermark" in terms
    assert len(terms) == len(set(terms)), f"duplicate negative terms: {negative}"


def test_user_negative_is_deduped_against_the_existing_terms() -> None:
    # "deformed" is already in the global guard; re-typing it must not double it.
    style = get_style("engraving")
    _, with_neg = wrap_prompt(style, "0001", _doc("a scene"), user_negative="deformed, cabbages")
    terms = [t.strip() for t in with_neg.split(",")]
    assert terms.count("deformed") == 1
    assert "cabbages" in terms


def test_absent_user_negative_is_byte_identical_to_before() -> None:
    # None and "" must both be no-ops — existing books/fixtures render the same negative.
    style = get_style("engraving")
    baseline = wrap_prompt(style, "0001", _doc("a scene", avoid=["fog"]))[1]
    for empty in (None, ""):
        doc = _doc("a scene", avoid=["fog"])
        _, negative = wrap_prompt(style, "0001", doc, user_negative=empty)
        assert negative == baseline


def test_user_negative_reaches_pseudo_plates_too() -> None:
    # A portrait/cover pseudo-plate still gets the owner's book-wide avoids appended.
    style = get_style("engraving")
    _, negative = wrap_prompt(
        style, "portrait-zossima", _doc("engraved bust"), user_negative="text, watermark"
    )
    terms = [t.strip() for t in negative.split(",")]
    assert "two people" in terms  # portrait guard still there
    assert "text" in terms and "watermark" in terms


def test_pseudo_plates_pass_their_prompt_through_but_still_get_the_guards() -> None:
    # cover/portrait strings were fully assembled by P5 (style baked in) — P7 must not re-wrap them.
    style = get_style("engraving")
    doc = _doc("engraved bust of the clockmaker", shot="wide")
    for plate_id in ("cover", "portrait-clockmaker"):
        wrapped, negative = wrap_prompt(style, plate_id, doc, "Russia 1870s")
        assert wrapped == "engraved bust of the clockmaker"
        assert "duplicate" in negative and style["negative"].split(",")[0] in negative


# --- ADR-0028: conditioning strength scales with how many figures are in frame ---


def test_single_figure_plate_accepts_the_service_conditioning_defaults() -> None:
    assert reference_conditioning(["Pyotr Ilyitch"]) == (None, None)


def test_no_depicted_characters_accepts_the_service_defaults() -> None:
    assert reference_conditioning([]) == (None, None)
    assert reference_conditioning(None) == (None, None)


def test_multi_figure_plate_gets_a_weaker_later_anchor() -> None:
    # IP-Adapter is global and unmasked: on a two-person plate the second person otherwise
    # inherits the anchor's face and clothes. 288 of 440 plates on the sample book were like this.
    strength, start = reference_conditioning(["Mitya", "Grushenka"])
    assert strength is not None and start is not None
    solo_strength, solo_start = 0.5, 0.3  # the imagegen-service defaults a solo plate would use
    assert strength < solo_strength, "a crowded frame must not be anchored as hard as a solo one"
    assert start > solo_start, "and identity must land later, after composition is settled"


def test_three_figure_plate_is_treated_like_any_other_multi_figure_plate() -> None:
    assert reference_conditioning(["A", "B", "C"]) == reference_conditioning(["A", "B"])


def test_portrait_plate_negative_bans_a_second_sitter() -> None:
    # A portrait is the reference for every plate its character anchors, so a two-figure portrait
    # is not one bad picture — it is every plate that character appears on.
    style = get_style("engraving")
    _, negative = wrap_prompt(style, "portrait-zossima", _doc("engraved bust of the elder"))
    assert "two people" in negative
    assert "group portrait" in negative


def test_page_plate_negative_does_not_carry_the_portrait_only_terms() -> None:
    # Page plates legitimately depict more than one person; banning "two people" there would
    # fight the prompt.
    style = get_style("engraving")
    _, negative = wrap_prompt(style, "0001", _doc("two men at a bench", depicted=["A", "B"]))
    assert "group portrait" not in negative
    assert "duplicate" in negative  # the global anatomy guards still apply
