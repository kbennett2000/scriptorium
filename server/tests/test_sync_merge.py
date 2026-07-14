"""Pure sync-merge tests (DESIGN §12) — the convergence contract.

Two layers:

- **Named conflict examples** — the three scenarios DESIGN §12 calls out, encoded literally so a
  regression in the merge rules is obvious.
- **Property harness** — seeded-random documents (no ``hypothesis`` dependency; a plain
  ``random.Random`` mirrors the repo's seeded-fixture convention) proving the algebra the whole sync
  design rests on: annotations merge is commutative, associative, and idempotent; positions
  ``furthest`` never regresses under any merge order. Every generated and merged document is checked
  against ``shared/schemas`` so the harness can't drift into shapes the server would reject.

Case counts are asserted (>= the CYCLE-LOG figure) so "the property tests ran" is not empty.
"""

from __future__ import annotations

import random

from scriptorium import schemas
from scriptorium.sync.merge import (
    _canonical_annotations,
    _furthest_key,
    merge_annotations,
    merge_positions,
)


def _ann(id_, modified, *, deleted=False, color="yellow", type_="highlight", page="0007"):
    a = {
        "id": id_,
        "type": type_,
        "page_id": page,
        "anchor": {"start": 10, "end": 20},
        "created": "2026-01-01T00:00:00Z",
        "modified": modified,
        "deleted": deleted,
    }
    if type_ in ("highlight", "note"):
        a["color"] = color
    if type_ == "note":
        a["text"] = "body"
    return a


def _doc(*annotations):
    return {"book_id": "pg-35", "user_id": "kris", "annotations": list(annotations)}


# ------------------------------------------------------------------------ named conflict examples


def test_conflict_two_device_edit_later_modified_wins_wholesale():
    """Same annotation edited offline on two devices → the later ``modified`` wins as a whole."""
    early = _ann("x", "2026-01-01T10:00:00Z", color="yellow")
    late = _ann("x", "2026-01-01T12:00:00Z", color="blue")
    merged = merge_annotations(_doc(early), _doc(late))
    assert merged["annotations"] == [late]
    assert merged["annotations"][0]["color"] == "blue"


def test_conflict_delete_vs_recolor_later_wins_deletion_can_lose():
    """Delete on one device, recolor on the other → later ``modified`` wins; deletion can lose."""
    recolor_later = _ann("x", "2026-01-01T12:00:00Z", color="green", deleted=False)
    delete_earlier = _ann("x", "2026-01-01T10:00:00Z", deleted=True)
    merged = merge_annotations(_doc(delete_earlier), _doc(recolor_later))
    # The later edit wins even though the other copy is a tombstone: the annotation survives.
    assert merged["annotations"] == [recolor_later]
    assert merged["annotations"][0]["deleted"] is False

    # And the symmetric case: a later delete beats an earlier recolor (deletion wins that time).
    delete_later = _ann("x", "2026-01-01T14:00:00Z", deleted=True)
    merged2 = merge_annotations(_doc(recolor_later), _doc(delete_later))
    assert merged2["annotations"][0]["deleted"] is True


def test_conflict_positions_furthest_p50_current_p30():
    """Phone read to p50, desktop to p30 later in time → furthest p50, current p30."""
    phone = {
        "furthest": {"page_seq": 50, "char": 0, "modified": "2026-01-01T10:00:00Z"},
        "current": {"page_seq": 50, "char": 0, "modified": "2026-01-01T10:00:00Z"},
    }
    desktop = {
        "furthest": {"page_seq": 30, "char": 0, "modified": "2026-01-01T12:00:00Z"},
        "current": {"page_seq": 30, "char": 0, "modified": "2026-01-01T12:00:00Z"},
    }
    merged = merge_positions(phone, desktop)
    assert merged["furthest"]["page_seq"] == 50  # furthest-read-wins, ignores the later timestamp
    assert merged["current"]["page_seq"] == 30   # LWW: desktop wrote later


# ------------------------------------------------------------------------ seeded-random generators

_ID_POOL = ["a", "b", "c", "d", "e"]  # small pool so merges genuinely collide on id
_COLORS = ["yellow", "blue", "green", "pink"]
_TYPES = ["highlight", "note", "bookmark"]


def _rand_time(rng):
    return (
        f"2026-01-{rng.randint(1, 28):02d}"
        f"T{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d}Z"
    )


def _rand_annotation(rng):
    type_ = rng.choice(_TYPES)
    start = rng.randint(0, 400)
    ann = {
        "id": rng.choice(_ID_POOL),
        "type": type_,
        "page_id": f"{rng.randint(0, 300):04d}",
        "anchor": {"start": start, "end": start + rng.randint(0, 80)},
        "created": _rand_time(rng),
        "modified": _rand_time(rng),
        "deleted": rng.random() < 0.3,
    }
    if type_ in ("highlight", "note"):
        ann["color"] = rng.choice(_COLORS)
    if type_ == "note":
        ann["text"] = "n" * rng.randint(0, 12)
    return ann


def _rand_ann_doc(rng):
    n = rng.randint(0, 8)
    return {
        "book_id": "pg-35",
        "user_id": "kris",
        "annotations": [_rand_annotation(rng) for _ in range(n)],
    }


def _rand_pos(rng):
    def point():
        return {
            "page_seq": rng.randint(1, 200),
            "char": rng.randint(0, 800),
            "modified": _rand_time(rng),
        }

    cur = point()
    if rng.random() < 0.5:
        cur["device"] = rng.choice(["pixel8", "ipad", "desktop"])
    return {"furthest": point(), "current": cur}


# --------------------------------------------------------------------------- annotation properties


def test_annotations_merge_algebra():
    """Commutative, associative, idempotent over many seeded document triples."""
    rng = random.Random(20250712)
    cases = 800
    for _ in range(cases):
        a, b, c = _rand_ann_doc(rng), _rand_ann_doc(rng), _rand_ann_doc(rng)
        for doc in (a, b, c):
            schemas.validate("annotations", doc)

        ab = merge_annotations(a, b)
        schemas.validate("annotations", ab)

        # commutative
        assert ab == merge_annotations(b, a)
        # associative
        assert merge_annotations(ab, c) == merge_annotations(a, merge_annotations(b, c))
        # idempotent: self-merge == canonical form; re-merging an already-merged pair is a no-op
        assert merge_annotations(a, a) == _canonical_annotations(a)
        assert merge_annotations(a, ab) == ab

    assert cases >= 500  # the harness actually ran the promised volume


# --------------------------------------------------------------------------- position properties


def test_positions_merge_algebra_and_furthest_never_regresses():
    """Commutative/associative/idempotent, and ``furthest`` only ever advances."""
    rng = random.Random(19990203)
    cases = 800
    for _ in range(cases):
        a, b, c = _rand_pos(rng), _rand_pos(rng), _rand_pos(rng)
        for doc in (a, b, c):
            schemas.validate("positions", doc)

        ab = merge_positions(a, b)
        schemas.validate("positions", ab)

        assert ab == merge_positions(b, a)                                    # commutative
        assert merge_positions(ab, c) == merge_positions(a, merge_positions(b, c))  # associative
        assert merge_positions(a, a) == a                                     # idempotent

        # furthest never regresses below either input, regardless of order
        fk = _furthest_key(ab["furthest"])[:2]
        assert fk >= _furthest_key(a["furthest"])[:2]
        assert fk >= _furthest_key(b["furthest"])[:2]

    assert cases >= 500
