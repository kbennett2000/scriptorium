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
