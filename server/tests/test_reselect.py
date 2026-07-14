"""Re-selection diff — merging a fresh selection into an existing one (DESIGN §8).

Covers the four cases named in the S7 plan — denser (adds only), sparser (rendered → retired,
never-rendered dropped), overlap (rendered + re-chosen stays rendered), manual preserved — plus
the retired-revive edge and result ordering.
"""

from __future__ import annotations

from scriptorium.selection.engine import PlateChoice
from scriptorium.selection.reselect import reselect


def _existing(page_id: str, *, reason: str = "fill", salience: float = 0.6,
              status: str = "rendered", rev: int = 1) -> dict:
    return {"page_id": page_id, "reason": reason, "salience": salience,
            "status": status, "added_in_revision": rev}


def _fresh(page_id: str, *, reason: str = "fill", salience: float = 0.6) -> PlateChoice:
    return PlateChoice(page_id, reason, salience)


def test_denser_adds_only_and_keeps_rendered() -> None:
    existing = [_existing("0001"), _existing("0003"), _existing("0005")]
    fresh = [_fresh(p) for p in ("0001", "0002", "0003", "0004", "0005")]

    merged = reselect(fresh, existing, revision=2)
    by_id = {p["page_id"]: p for p in merged}

    assert set(by_id) == {"0001", "0002", "0003", "0004", "0005"}
    # Re-chosen rendered plates are untouched (no re-render), revision preserved.
    for pid in ("0001", "0003", "0005"):
        assert by_id[pid]["status"] == "rendered"
        assert by_id[pid]["added_in_revision"] == 1
    # New plates are selected at the new revision.
    for pid in ("0002", "0004"):
        assert by_id[pid]["status"] == "selected"
        assert by_id[pid]["added_in_revision"] == 2
    # Additive: nothing retired when the selection only grows.
    assert all(p["status"] != "retired" for p in merged)


def test_sparser_retires_rendered_and_drops_never_rendered() -> None:
    existing = [_existing(p) for p in ("0001", "0002", "0003", "0004", "0005")]
    existing.append(_existing("0006", status="selected"))  # never rendered
    fresh = [_fresh("0001"), _fresh("0005")]

    merged = reselect(fresh, existing, revision=2)
    by_id = {p["page_id"]: p for p in merged}

    # Rendered + re-chosen stay rendered.
    assert by_id["0001"]["status"] == "rendered"
    assert by_id["0005"]["status"] == "rendered"
    # Rendered + not re-chosen retire (files kept — entry survives).
    for pid in ("0002", "0003", "0004"):
        assert by_id[pid]["status"] == "retired"
        assert by_id[pid]["added_in_revision"] == 1
    # Never-rendered + not re-chosen is dropped (no pixels to preserve).
    assert "0006" not in by_id


def test_overlap_rendered_rechosen_stays_rendered_with_refreshed_reason() -> None:
    existing = [_existing("0003", reason="fill", salience=0.60, status="rendered", rev=1)]
    fresh = [_fresh("0003", reason="chapter_open", salience=0.90)]

    merged = reselect(fresh, existing, revision=3)
    assert len(merged) == 1
    plate = merged[0]
    assert plate["status"] == "rendered"  # no re-render
    assert plate["added_in_revision"] == 1  # first-selected revision preserved
    assert plate["reason"] == "chapter_open"  # reason/salience refresh to the new run
    assert plate["salience"] == 0.90


def test_manual_entries_are_preserved_verbatim() -> None:
    existing = [
        _existing("0007", reason="manual", status="approved", rev=1),
        _existing("0002", status="rendered", rev=1),
    ]
    # A fresh run that also happens to pick 0007 must not clobber the manual entry.
    fresh = [_fresh("0007", reason="fill"), _fresh("0002")]

    merged = reselect(fresh, existing, revision=2)
    manuals = [p for p in merged if p["page_id"] == "0007"]
    assert len(manuals) == 1  # exactly one 0007 entry — the manual one
    assert manuals[0]["reason"] == "manual"
    assert manuals[0]["status"] == "approved"


def test_manual_removal_target_not_reintroduced_by_fresh_run() -> None:
    # A manual entry survives even when the fresh run does not re-pick it.
    existing = [_existing("0009", reason="manual", status="rendered", rev=1)]
    merged = reselect([], existing, revision=2)
    assert [p["page_id"] for p in merged] == ["0009"]
    assert merged[0]["reason"] == "manual"


def test_retired_plate_is_revived_when_rechosen() -> None:
    existing = [_existing("0002", reason="fill", status="retired", rev=1)]
    fresh = [_fresh("0002", reason="scene_boundary", salience=0.70)]

    merged = reselect(fresh, existing, revision=4)
    assert len(merged) == 1
    assert merged[0]["status"] == "selected"
    assert merged[0]["added_in_revision"] == 1  # original selection revision kept
    assert merged[0]["reason"] == "scene_boundary"


def test_approved_rechosen_keeps_approved_but_dropped_when_not() -> None:
    existing = [_existing("0002", status="approved", rev=1),
                _existing("0003", status="approved", rev=1)]
    fresh = [_fresh("0002")]  # 0002 re-chosen, 0003 not

    merged = reselect(fresh, existing, revision=2)
    by_id = {p["page_id"]: p for p in merged}
    assert by_id["0002"]["status"] == "approved"
    assert "0003" not in by_id  # approved but never rendered and not re-chosen → dropped


def test_result_is_sorted_by_page_id() -> None:
    existing = [_existing("0005"), _existing("0001"), _existing("0003")]
    fresh = [_fresh(p) for p in ("0005", "0001", "0003")]
    merged = reselect(fresh, existing, revision=2)
    ids = [p["page_id"] for p in merged]
    assert ids == sorted(ids) == ["0001", "0003", "0005"]
