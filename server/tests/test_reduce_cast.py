"""Reducer unit tests (DESIGN §7.2) — the named, mandatory edge cases.

``reduce_cast`` is a pure function, so these feed hand-built mention lists and assert on the
grouping only (never LLM content). Covered: the Weena/Eloi co-occurrence guard, the
Mr.-Hillyer/Hillyer honorific merge, possessive stripping, the ≥3/top-6 major rule (both
branches), slug uniquing, and the approved pronoun-drop amendment.
"""

from __future__ import annotations

from typing import Any

from scriptorium.bake.reduce_cast import reduce_cast


def _m(name: str, aliases: list[str] | None = None,
       descriptors: list[str] | None = None, is_person: bool = True) -> dict[str, Any]:
    return {"name": name, "aliases": aliases or [], "descriptors": descriptors or [],
            "is_person": is_person}


def _page(pid: str, *mentions: dict[str, Any]) -> dict[str, Any]:
    return {"page_id": pid, "mentions": list(mentions)}


def _by_slug(groups: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {g["slug"]: g for g in groups}


def test_cooccurrence_guard_keeps_eloi_out_of_weena() -> None:
    # Weena and Eloi appear as distinct entries on the same page → never merged, even though
    # "little Weena" ⊂-merges into Weena.
    groups = reduce_cast([
        _page("0001", _m("Weena"), _m("Eloi")),
        _page("0002", _m("little Weena"), _m("Eloi")),
        _page("0003", _m("Weena")),
    ])
    slugs = _by_slug(groups)
    assert "weena" in slugs and "eloi" in slugs
    assert "little Weena" in slugs["weena"]["aliases"]
    assert "Eloi" not in slugs["weena"]["aliases"]
    assert slugs["weena"]["mention_pages"] == ["0001", "0002", "0003"]
    assert slugs["eloi"]["mention_pages"] == ["0001", "0002"]


def test_honorific_merge_mr_hillyer() -> None:
    groups = reduce_cast([
        _page("0001", _m("Mr. Hillyer")),
        _page("0002", _m("Mr. Hillyer")),
        _page("0003", _m("Hillyer")),
    ])
    assert len(groups) == 1
    g = groups[0]
    assert g["name"] == "Mr. Hillyer"  # most-frequent full label
    assert "Hillyer" in g["aliases"]
    assert g["mention_pages"] == ["0001", "0002", "0003"]


def test_possessive_strip_merges_and_display_is_most_frequent() -> None:
    groups = reduce_cast([
        _page("0001", _m("Weena's")),
        _page("0002", _m("Weena")),
        _page("0003", _m("Weena")),
    ])
    assert len(groups) == 1
    assert groups[0]["name"] == "Weena"  # possessive form matched but is the minority display
    assert groups[0]["mention_pages"] == ["0001", "0002", "0003"]


def _pages_from_counts(counts: dict[str, int]) -> list[dict[str, Any]]:
    """Build pages so each name appears on exactly ``counts[name]`` pages (stable order)."""
    max_pages = max(counts.values())
    pages = []
    for i in range(max_pages):
        present = [_m(name) for name, n in counts.items() if n > i]
        pages.append(_page(f"{i + 1:04d}", *present))
    return pages


def test_major_rule_top6_when_that_set_is_larger() -> None:
    counts = {"Alpha": 5, "Bravo": 4, "Charlie": 3, "Delta": 2,
              "Echo": 2, "Foxtrot": 2, "Golf": 1, "Hotel": 1}
    groups = _by_slug(reduce_cast(_pages_from_counts(counts)))
    # ≥3-pages set = {Alpha,Bravo,Charlie} (3); top-6 = 6 → top-6 wins.
    majors = {s for s, g in groups.items() if g["major"]}
    assert majors == {"alpha", "bravo", "charlie", "delta", "echo", "foxtrot"}
    assert not groups["golf"]["major"] and not groups["hotel"]["major"]


def test_major_rule_floor_when_that_set_is_larger() -> None:
    counts = {"Alpha": 5, "Bravo": 5, "Charlie": 4, "Delta": 4,
              "Echo": 3, "Foxtrot": 3, "Golf": 3, "Hotel": 1}
    groups = _by_slug(reduce_cast(_pages_from_counts(counts)))
    # ≥3-pages set = 7 names; top-6 = 6 → the ≥3 set wins.
    majors = {s for s, g in groups.items() if g["major"]}
    assert majors == {"alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf"}
    assert not groups["hotel"]["major"]


def test_non_person_never_auto_major() -> None:
    groups = _by_slug(reduce_cast([
        _page("0001", _m("the Morlocks", is_person=False)),
        _page("0002", _m("the Morlocks", is_person=False)),
        _page("0003", _m("the Morlocks", is_person=False)),
    ]))
    assert groups["morlocks"]["is_person"] is False
    assert groups["morlocks"]["major"] is False


def test_slug_uniquing_suffixes_collisions() -> None:
    # Two distinct guards co-occur (guard blocks the ⊂-merge) but slug identically.
    groups = reduce_cast([
        _page("0001", _m("the Guard"), _m("Guard")),
        _page("0002", _m("the Guard")),
    ])
    slugs = sorted(g["slug"] for g in groups)
    assert slugs == ["guard", "guard-2"]


def test_bare_pronouns_dropped_before_grouping() -> None:
    groups = reduce_cast([
        _page("0001", _m("I", descriptors=["the narrator"]), _m("the Time Traveller")),
        _page("0002", _m("He"), _m("She"), _m("the Time Traveller")),
    ])
    slugs = _by_slug(groups)
    assert set(slugs) == {"time-traveller"}  # every pronoun mention dropped


# --- ADR-0019: extended stop-words, junk filtering, alias safety -------------


def test_object_pronoun_me_dropped() -> None:
    # "me" (object pronoun) is a stop-word now; it must not survive as a character.
    groups = reduce_cast([
        _page("0001", _m("me", descriptors=["the narrator"]), _m("Alyosha")),
        _page("0002", _m("Alyosha")),
    ])
    slugs = _by_slug(groups)
    assert "me" not in slugs
    assert set(slugs) == {"alyosha"}


def test_reflexive_and_indefinite_names_dropped() -> None:
    groups = reduce_cast([
        _page("0001", _m("himself"), _m("someone"), _m("nobody"), _m("Ivan")),
        _page("0002", _m("Ivan")),
    ])
    assert set(_by_slug(groups)) == {"ivan"}


def test_lowercase_generic_role_dropped_capitalized_kept() -> None:
    # Single-page all-lowercase generic nouns are junk; capitalized designations are kept.
    groups = reduce_cast([
        _page("0001", _m("peasant"), _m("the Time Traveller")),
        _page("0002", _m("old woman"), _m("another female figure"), _m("the Psychologist")),
    ])
    assert set(_by_slug(groups)) == {"time-traveller", "psychologist"}


def test_lowercase_role_kept_when_recurring() -> None:
    # A lowercase role on >= 2 pages is a real recurring referent, not junk.
    groups = reduce_cast([
        _page("0001", _m("mother")),
        _page("0002", _m("mother")),
    ])
    assert "mother" in _by_slug(groups)


def test_shared_patronymic_token_merges_nobody() -> None:
    # A bare shared patronymic must never bridge two people who only share it (A2).
    groups = reduce_cast([
        _page("0001", _m("Dmitri Fyodorovitch")),
        _page("0002", _m("Alexey Fyodorovitch")),
        _page("0003", _m("Fyodorovitch")),
    ])
    slugs = _by_slug(groups)
    assert len(groups) == 3
    assert slugs["dmitri-fyodorovitch"]["mention_pages"] == ["0001"]
    assert slugs["alexey-fyodorovitch"]["mention_pages"] == ["0002"]


def test_given_name_merges_across_cooccurrence() -> None:
    # "Dmitri" and "Dmitri Fyodorovitch" as distinct same-page entries are one person: an
    # unambiguous multi-token containment merges even across the co-occurrence guard (A3).
    groups = reduce_cast([
        _page("0001", _m("Dmitri"), _m("Dmitri Fyodorovitch")),
        _page("0002", _m("Dmitri Fyodorovitch")),
    ])
    assert len(groups) == 1
    g = groups[0]
    assert g["mention_pages"] == ["0001", "0002"]  # exact page union (ADR-0008)
    assert "Dmitri" in g["aliases"]


def test_junk_lowercase_single_page_never_survives_as_major() -> None:
    # A single-page lowercase "peasant" is dropped, so it can never be canonicalized or portraited.
    groups = reduce_cast([
        _page("0001", _m("peasant"), _m("the Time Traveller")),
        _page("0002", _m("the Time Traveller")),
        _page("0003", _m("the Time Traveller")),
    ])
    slugs = _by_slug(groups)
    assert "peasant" not in slugs
    assert not any(g["name"] == "peasant" for g in groups)
    assert slugs["time-traveller"]["major"] is True


def test_pronoun_aliases_are_dropped_from_published_group() -> None:
    # cast-mentions sometimes lists pronouns (incl. archaic "Thou") inside a character's aliases.
    # They must never reach cast.json — left in, present_cast would match them against a ledger.
    groups = reduce_cast([
        _page("0001", _m("Mitya", aliases=["He", "him", "His", "Thou", "Mityenka"])),
        _page("0002", _m("Mitya")),
    ])
    g = groups[0]
    assert "Mityenka" in g["aliases"]                         # a real surface variant survives
    for pron in ("He", "him", "His", "Thou"):
        assert pron not in g["aliases"]


def test_another_characters_name_is_dropped_from_aliases() -> None:
    # A bogus alias equal to a DIFFERENT character's canonical name is contamination: it would make
    # present_cast pull the wrong character into a scene. It must be filtered out.
    groups = reduce_cast([
        _page("0001", _m("Marfa Ignatyevna", aliases=["Grigory", "Marfa"]), _m("Grigory")),
        _page("0002", _m("Marfa Ignatyevna"), _m("Grigory")),
        _page("0003", _m("Grigory")),
    ])
    slugs = _by_slug(groups)
    marfa = slugs["marfa-ignatyevna"]["aliases"]
    assert "Marfa" in marfa          # own surface variant kept
    assert "Grigory" not in marfa    # other character's canonical name dropped
    assert slugs["grigory"]["name"] == "Grigory"  # Grigory stays its own character


def test_cleaned_aliases_stop_present_cast_cross_link() -> None:
    # End-to-end (in-repo): with the contaminating "Grigory" alias filtered out, a page whose ledger
    # lists only Marfa no longer drags Grigory into the illustration cast.
    from scriptorium.bake.phases.p5_prompts import present_cast

    groups = reduce_cast([
        _page("0001", _m("Marfa Ignatyevna", aliases=["Grigory"]), _m("Grigory")),
        _page("0002", _m("Marfa Ignatyevna"), _m("Grigory")),
        _page("0003", _m("Grigory")),
    ])
    cast_doc = {"characters": [{**g, "one_line": ""} for g in groups]}
    present = present_cast(cast_doc, {"present": ["Marfa Ignatyevna"]})
    names = {c["name"] for c in present}
    assert "Marfa Ignatyevna" in names
    assert "Grigory" not in names  # no cross-link — the whole point of the filter


def test_alias_claimed_by_several_characters_is_dropped_from_all() -> None:
    # ADR-0027: an alias attached to more than one character identifies nobody and guarantees a
    # cross-link. On a real 239-character book "the old man" was claimed by NINE characters and
    # "Dmitri Fyodorovitch" by six. Drop it everywhere rather than pick a winner.
    groups = reduce_cast([
        _page("0001", _m("Fyodor Pavlovitch", aliases=["Karamazov", "Dmitri Fyodorovitch"])),
        _page("0002", _m("Grigory", aliases=["Dmitri Fyodorovitch"])),
        _page("0003", _m("Fyodor Pavlovitch"), _m("Grigory")),
    ])
    slugs = _by_slug(groups)
    assert "Karamazov" in slugs["fyodor-pavlovitch"]["aliases"]  # singly-claimed name survives
    for g in groups:
        assert "Dmitri Fyodorovitch" not in g["aliases"]


def test_alias_matching_another_name_modulo_title_is_dropped() -> None:
    # The pre-ADR-0027 rule compared canonical names verbatim, so an "elder" group carrying the
    # alias "Zossima" slipped past the group actually called "Father Zossima" — and every plate
    # naming Zossima then resolved ambiguously between the two.
    groups = reduce_cast([
        _page("0001", _m("the elder", aliases=["Zossima"]), _m("Father Zossima")),
        _page("0002", _m("the elder"), _m("Father Zossima")),
        _page("0003", _m("Father Zossima")),
    ])
    slugs = _by_slug(groups)
    assert "Zossima" not in slugs["elder"]["aliases"]
    assert slugs["father-zossima"]["name"] == "Father Zossima"


def test_uncapitalised_role_epithets_are_dropped_from_aliases() -> None:
    # ADR-0027: "the boy" / "brother" / "mamma" are roles, not names. They were the bulk of the
    # contamination (487 of 731 aliases on the sample book).
    groups = reduce_cast([
        _page("0001", _m("Alyosha", aliases=["the boy", "brother", "mamma", "Alexey"])),
        _page("0002", _m("Alyosha")),
    ])
    aliases = groups[0]["aliases"]
    assert "Alexey" in aliases  # a capitalised variant is a name and survives
    for junk in ("the boy", "brother", "mamma"):
        assert junk not in aliases
