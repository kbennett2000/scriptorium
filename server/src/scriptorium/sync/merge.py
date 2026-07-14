"""Server-authoritative sync merge — the convergence core (DESIGN §12).

Pure and FastAPI-free: clients send full documents and receive merged full documents, and these two
functions decide the outcome. Correctness rests on **order-independence** — two offline devices may
reconnect in either order, possibly repeatedly, and must converge to the same document. That is why
both functions are commutative, associative, and idempotent, proven by the property harness in
``tests/test_sync_merge.py``.

The functions never do I/O and never call the network; the endpoint layer (``sync/api.py``) wraps
them with schema validation, per-``(user, book)`` locking, and versioned backups.

Timestamps are compared as **ISO-8601 strings**: they are always UTC and always second-or-finer
precision (JS ``Date.toISOString()``), so lexicographic order equals chronological order — no
parsing needed, and a malformed-but-comparable string still yields a deterministic result.
"""

from __future__ import annotations

import json
from typing import Any

# Tombstones (deleted annotations) are retained at least this long so a device that was offline for
# a while still sees the deletion and converges. Actually *dropping* aged tombstones (compaction) is
# explicitly deferred: v1 keeps every tombstone forever, so this constant is documentation of the
# floor a future compactor must honor, not a value the merge currently enforces.
TOMBSTONE_RETENTION_DAYS = 180


def _annotation_sort_key(ann: dict[str, Any]) -> str:
    """Total, stable ordering of annotations by their merge key (``id``)."""
    return ann["id"]


def _annotation_pick_key(ann: dict[str, Any]) -> tuple[str, str]:
    """Which of two same-``id`` annotations wins: greater ``modified``, then a full-doc tiebreak.

    The tiebreak (canonical JSON of the whole annotation) only matters when two copies share an id
    *and* a ``modified`` timestamp; it guarantees the choice is independent of argument order, so
    the merge stays commutative even in that degenerate case.
    """
    return (ann["modified"], json.dumps(ann, sort_keys=True, ensure_ascii=False))


def _canonical_annotations(doc: dict[str, Any]) -> dict[str, Any]:
    """Return ``doc`` with its annotations deduplicated by id (winner kept) and sorted by id.

    Idempotency of :func:`merge_annotations` is defined against this canonical form — merging a
    document with itself yields exactly ``_canonical_annotations`` of it.
    """
    best: dict[str, dict[str, Any]] = {}
    for ann in doc.get("annotations", []):
        cur = best.get(ann["id"])
        if cur is None or _annotation_pick_key(ann) > _annotation_pick_key(cur):
            best[ann["id"]] = ann
    ordered = sorted(best.values(), key=_annotation_sort_key)
    return {
        "book_id": doc["book_id"],
        "user_id": doc["user_id"],
        "annotations": ordered,
    }


def merge_annotations(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Merge two annotation docs (DESIGN §12): union by ``id``, last-writer-wins by ``modified``.

    Tombstones (``deleted: true``) are ordinary entries — a deletion is just another edit and merges
    identically, so a later delete beats an earlier edit and a later edit beats an earlier delete
    (deletion can lose; documented and acceptable). Output is canonical: annotations sorted by
    ``id``, each id present once. Identity comes from ``a`` (falling back to ``b``); callers that
    know the ``(user, book)`` from the request path overwrite both fields authoritatively afterward.

    Commutative, associative, and idempotent (``merge(x, x) == _canonical_annotations(x)``).
    """
    identity = a if a.get("book_id") else b
    combined = {
        "book_id": identity["book_id"],
        "user_id": identity["user_id"],
        "annotations": list(a.get("annotations", [])) + list(b.get("annotations", [])),
    }
    return _canonical_annotations(combined)


def _furthest_key(pos: dict[str, Any]) -> tuple[int, int, str]:
    """Order for ``furthest``: by ``(page_seq, char)`` — furthest-read-wins. ``modified`` is only a
    deterministic tiebreak when the reading point is identical, so it can never flip the winner."""
    return (pos["page_seq"], pos["char"], pos["modified"])


def _current_key(pos: dict[str, Any]) -> tuple[str, int, int, str]:
    """Order for ``current``: last-writer-wins by ``modified``, with ``(page_seq, char, device)`` as
    a deterministic tiebreak so equal-timestamp writes (even differing only by ``device``) still
    merge order-independently."""
    return (pos["modified"], pos["page_seq"], pos["char"], pos.get("device", ""))


def merge_positions(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Merge two position documents (DESIGN §12).

    ``furthest`` = max by ``(page_seq, char)`` **regardless of timestamp** (furthest-read-wins, so
    it never regresses); ``current`` = greater ``modified`` (last-writer-wins). Commutative,
    associative, and idempotent.
    """
    furthest = max(a["furthest"], b["furthest"], key=_furthest_key)
    current = max(a["current"], b["current"], key=_current_key)
    return {"furthest": furthest, "current": current}
