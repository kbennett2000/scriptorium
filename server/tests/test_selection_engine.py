"""P4 selection engine — the pure ``select`` function (DESIGN §8).

Properties are asserted over a committed synthetic 120-page score field (12 chapters × 10 pages,
generated once with a fixed seed — see ``fixtures/selection/synthetic-120.json``). Per CLAUDE.md
the tests assert structure/invariants, never exact content: gap bounds, floor, mandatory marks,
precedence tie-breaks, determinism, and the structural spoiler invariant.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from scriptorium import schemas
from scriptorium.selection.engine import (
    PRESETS,
    PageScore,
    Params,
    page_score_fields,
    select,
)

_FIX = Path(__file__).parent / "fixtures" / "selection" / "synthetic-120.json"


def _load_synthetic() -> tuple[list[PageScore], dict]:
    fx = json.loads(_FIX.read_text(encoding="utf-8"))
    scores = [
        PageScore(
            seq=s["seq"], page_id=s["page_id"], chapter=s["chapter"],
            scene_changed=s["scene_changed"], visual_salience=s["visual_salience"],
        )
        for s in fx["scores"]
    ]
    return scores, fx["structure"]


def _score(seq: int, *, salience: float = 0.5, scene: bool = False, chapter: int = 1) -> PageScore:
    return PageScore(
        seq=seq, page_id=f"{seq:04d}", chapter=chapter,
        scene_changed=scene, visual_salience=salience,
    )


def _structure_from(scores: list[PageScore]) -> dict:
    """Build a structure whose chapter openers are the first page of each ``chapter`` group."""
    chapters: dict[int, list[str]] = {}
    for s in sorted(scores, key=lambda s: s.seq):
        chapters.setdefault(s.chapter, []).append(s.page_id)
    return {
        "chapters": [
            {"index": ci, "title": str(ci), "page_ids": pids}
            for ci, pids in sorted(chapters.items())
        ]
    }


# --- properties over the synthetic 120-page field ---------------------------


@pytest.mark.parametrize("preset", ["lavish", "classic", "sparse"])
def test_preset_properties_over_synthetic_field(preset: str) -> None:
    scores, structure = _load_synthetic()
    params = PRESETS[preset]
    plates = select(scores, structure, params)
    assert plates  # every preset picks at least the chapter openers

    ids = [int(p.page_id) for p in plates]
    # Sorted by seq, no duplicates.
    assert ids == sorted(ids)
    assert len(ids) == len(set(ids))

    # Property: no two plates closer than min_gap (the load-bearing acceptance property).
    assert all(b - a >= params.min_gap for a, b in zip(ids, ids[1:], strict=False))

    # Property: every fill plate clears the salience floor.
    assert all(p.salience >= params.salience_floor for p in plates if p.reason == "fill")

    # Property: every mandatory reason is a valid enum member; scene_boundary only if enabled.
    assert all(p.reason in {"chapter_open", "scene_boundary", "fill"} for p in plates)
    if not params.scene_boundary:
        assert all(p.reason != "scene_boundary" for p in plates)

    # Property: every chapter opener is present as chapter_open (chapters are ≥ min_gap apart
    # in the synthetic field, so no opener loses a min_gap collision).
    opener_ids = {c["page_ids"][0] for c in structure["chapters"]}
    by_id = {p.page_id: p for p in plates}
    assert all(oid in by_id and by_id[oid].reason == "chapter_open" for oid in opener_ids)


@pytest.mark.parametrize("preset", ["lavish", "classic", "sparse"])
def test_selection_is_deterministic(preset: str) -> None:
    scores, structure = _load_synthetic()
    first = select(scores, structure, PRESETS[preset])
    second = select(scores, structure, PRESETS[preset])
    assert first == second


def test_engine_output_builds_schema_valid_selection() -> None:
    scores, structure = _load_synthetic()
    plates = select(scores, structure, PRESETS["classic"])
    doc = {
        "preset": "classic",
        "params": PRESETS["classic"].as_dict(),
        "plates": [
            {"page_id": p.page_id, "reason": p.reason, "salience": p.salience,
             "status": "selected", "added_in_revision": 1}
            for p in plates
        ],
    }
    schemas.validate("selection", doc)  # raises on any schema violation


# --- precedence & tie-breaks (DESIGN §8 step 2) -----------------------------


def test_chapter_open_beats_scene_boundary_within_min_gap() -> None:
    # One chapter (opener 0001); a scene boundary at 0002 collides with it under classic min_gap=2.
    scores = [_score(1, salience=0.1)] + [
        _score(s, salience=0.1, scene=(s == 2)) for s in range(2, 9)
    ]
    plates = select(scores, _structure_from(scores), PRESETS["classic"])
    by_id = {p.page_id: p for p in plates}
    assert by_id["0001"].reason == "chapter_open"
    assert "0002" not in by_id  # the scene boundary lost to the chapter opener and was dropped


def test_scene_boundary_tiebreak_prefers_higher_salience() -> None:
    # Two colliding scene boundaries (0004,0005) under classic min_gap=2; higher salience wins.
    scores = [_score(1, salience=0.1)]
    scores += [_score(s, salience=0.1) for s in (2, 3)]
    scores += [_score(4, salience=0.90, scene=True), _score(5, salience=0.30, scene=True)]
    scores += [_score(s, salience=0.1) for s in (6, 7, 8)]
    plates = select(scores, _structure_from(scores), PRESETS["classic"])
    by_id = {p.page_id: p for p in plates}
    assert by_id["0004"].reason == "scene_boundary"
    assert "0005" not in by_id


def test_scene_boundary_tiebreak_prefers_earlier_seq_on_equal_salience() -> None:
    scores = [_score(1, salience=0.1)]
    scores += [_score(s, salience=0.1) for s in (2, 3)]
    scores += [_score(4, salience=0.80, scene=True), _score(5, salience=0.80, scene=True)]
    scores += [_score(s, salience=0.1) for s in (6, 7, 8)]
    plates = select(scores, _structure_from(scores), PRESETS["classic"])
    by_id = {p.page_id: p for p in plates}
    assert "0004" in by_id and by_id["0004"].reason == "scene_boundary"
    assert "0005" not in by_id  # equal salience → earlier seq kept


# --- short books honor chapters + density (no more tiny-work collapse) ------


def test_short_multichapter_book_gets_a_plate_per_chapter() -> None:
    # 4 one-page chapters — each chapter opener is a mandatory mark (min_gap=1 for lavish).
    scores = [_score(s, salience=0.2, chapter=s) for s in range(1, 5)]
    plates = select(scores, _structure_from(scores), PRESETS["lavish"])
    assert [p.page_id for p in plates] == ["0001", "0002", "0003", "0004"]
    assert all(p.reason == "chapter_open" for p in plates)


def test_density_still_changes_count_for_short_books() -> None:
    # A 6-page single chapter with one salient page: lavish fills, classic/sparse fit within
    # max_gap so they stay at the sole opener. Density is no longer a no-op below 8 pages.
    scores = [_score(s, salience=0.2) for s in range(1, 7)]
    scores[3] = _score(4, salience=0.95)  # a strong page mid-book
    struct = _structure_from(scores)
    lavish = {p.page_id for p in select(scores, struct, PRESETS["lavish"])}
    classic = {p.page_id for p in select(scores, struct, PRESETS["classic"])}
    assert lavish == {"0001", "0004"}   # gap 1->6 exceeds lavish max_gap(3) → fills the strong page
    assert classic == {"0001"}          # gap 1->6 within classic max_gap(6) → no fill
    assert lavish > classic


def test_single_page_book_still_yields_one_plate() -> None:
    scores = [_score(1, salience=0.2)]
    plates = select(scores, _structure_from(scores), PRESETS["lavish"])
    assert [p.page_id for p in plates] == ["0001"]
    assert plates[0].reason == "chapter_open"


# --- pathological: all-low-salience (DESIGN §8 step 3 skip) -----------------


def test_all_low_salience_forces_no_fill_and_gaps_exceed_max_gap() -> None:
    # 30 pages, one chapter, every salience below the classic floor, no scene changes.
    scores = [_score(s, salience=0.10, chapter=1) for s in range(1, 31)]
    params = PRESETS["classic"]
    plates = select(scores, _structure_from(scores), params)
    # Only the single chapter opener survives; nothing is forced into a weak fill.
    assert [p.page_id for p in plates] == ["0001"]
    assert all(p.reason != "fill" for p in plates)
    # The gap from the sole plate to the book's end far exceeds max_gap (gaps are allowed to).
    assert 30 - 1 > params.max_gap


# --- structural spoiler invariant -------------------------------------------


def test_pagescore_carries_no_text_field() -> None:
    # The spoiler invariant is enforced by the type: numbers/booleans + the id only.
    assert set(page_score_fields()) == {
        "seq", "page_id", "chapter", "scene_changed", "visual_salience",
    }
    # No free-text/content field ever leaked in.
    forbidden = {"text", "location", "atmosphere", "best_visual_beat", "carry_notes",
                 "present", "title"}
    assert not (set(page_score_fields()) & forbidden)
    # And it is frozen, so selection cannot be handed a mutable content-bearing record.
    assert dataclasses.fields(PageScore)  # is a dataclass
    assert PageScore.__dataclass_params__.frozen


def test_params_as_dict_matches_preset_table() -> None:
    assert PRESETS["classic"].as_dict() == {
        "min_gap": 2, "max_gap": 6, "salience_floor": 0.55,
        "chapter_open": True, "scene_boundary": True,
    }
    assert isinstance(PRESETS["sparse"], Params)
    assert PRESETS["sparse"].scene_boundary is False
