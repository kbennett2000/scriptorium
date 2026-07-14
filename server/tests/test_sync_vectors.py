"""The Python half of the shared sync-merge contract (DESIGN §12).

Both the server (`scriptorium.sync.merge`) and the TypeScript reader (`reader/src/sync/merge.ts`)
merge annotation and position documents identically — union-by-id LWW for annotations,
furthest-wins + current-LWW for positions, with deterministic full-field tiebreaks. The two impls
are pinned against ONE vector file — `shared/test-vectors/sync-merge.json` — so a drift in either
surfaces as a red suite here or in `reader/src/sync/merge.test.ts`. Every case is run in BOTH orders
to pin commutativity.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scriptorium.sync.merge import merge_annotations, merge_positions

_VECTORS = Path(__file__).resolve().parents[2] / "shared" / "test-vectors" / "sync-merge.json"


def _load() -> dict:
    return json.loads(_VECTORS.read_text(encoding="utf-8"))


def _ann_cases() -> list[dict]:
    return _load()["annotations"]


def _pos_cases() -> list[dict]:
    return _load()["positions"]


@pytest.mark.parametrize("case", _ann_cases(), ids=lambda c: c["name"])
def test_shared_annotation_vector(case: dict) -> None:
    assert merge_annotations(case["a"], case["b"]) == case["expected"]
    assert merge_annotations(case["b"], case["a"]) == case["expected"]


@pytest.mark.parametrize("case", _pos_cases(), ids=lambda c: c["name"])
def test_shared_position_vector(case: dict) -> None:
    assert merge_positions(case["a"], case["b"]) == case["expected"]
    assert merge_positions(case["b"], case["a"]) == case["expected"]
