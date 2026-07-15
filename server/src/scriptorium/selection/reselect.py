"""Re-selection diff — merge a fresh selection into an existing one (DESIGN §8).

When the density knob is re-turned on an already-baked book, :func:`select` is re-run fresh and
the result is diffed against the existing ``selection.json`` plates. The merge is **additive**:
rendered plates and their files are never discarded, only transitioned to ``retired``.

The rules (DESIGN §8 "Re-selection" + §11.3 manual overrides):

- **Manual** entries (``reason == "manual"``) pass through untouched — they are human add/remove
  decisions and are authoritative over the automatic run.
- A page **re-chosen** that was previously **rendered** stays ``rendered`` (no re-render); its
  ``added_in_revision`` is preserved and its reason/salience refresh to the new run.
- A page re-chosen that was ``selected``/``approved`` keeps that status (``added_in_revision``
  preserved).
- A page re-chosen that was ``retired`` is revived to ``selected`` (keeping its original
  ``added_in_revision``).
- A **new** page becomes ``selected`` with ``added_in_revision = revision``.
- A previously **rendered** page **not** re-chosen becomes ``retired`` (entry and files kept —
  the additive invariant).
- A ``retired`` page not re-chosen stays ``retired``.
- A **never-rendered, non-manual** page (``selected``/``approved``) not re-chosen is **dropped**:
  it has no pixels to preserve, so the additive invariant does not apply. (This is the one place
  a human ``approved`` on an *unrendered* plate is discarded — a deliberate reading of §8.)

Only ``selected`` plates flow onward to prompt derivation and render.
"""

from __future__ import annotations

from .engine import MANUAL, PlateChoice


def _effective_id(plate: dict) -> str:
    """A plate's diff key / filename stem: its compound ``plate_id`` or its bare ``page_id``."""
    return plate.get("plate_id") or plate["page_id"]


def _plate(
    page_id: str,
    reason: str,
    salience: float,
    status: str,
    added_in_revision: int,
    *,
    plate_id: str | None = None,
    anchor: int | None = None,
    segment_index: int | None = None,
) -> dict:
    # Compound fields are emitted only for evenly-spaced extras, so a page's base plate stays
    # byte-identical to a single-image bake (field order matches P4's serializer).
    doc: dict = {"page_id": page_id}
    if plate_id is not None and plate_id != page_id:
        doc["plate_id"] = plate_id
    if anchor is not None:
        doc["anchor"] = anchor
    if segment_index is not None:
        doc["segment_index"] = segment_index
    doc.update({
        "reason": reason,
        "salience": salience,
        "status": status,
        "added_in_revision": added_in_revision,
    })
    return doc


def reselect(
    fresh: list[PlateChoice], existing_plates: list[dict], *, revision: int
) -> list[dict]:
    """Merge a ``fresh`` selection into ``existing_plates`` for ``revision`` (DESIGN §8).

    ``revision`` is the new bundle revision (``current + 1``). Diffing is keyed on each plate's
    **effective id** (``plate_id`` or ``page_id``), so a page's evenly-spaced extras are tracked
    independently of its base image. Returns the merged plate list, sorted by effective id.
    """
    fresh_by_id = {c.effective_id: c for c in fresh}
    manual_ids = {_effective_id(p) for p in existing_plates if p.get("reason") == MANUAL}
    existing_by_id = {_effective_id(p): p for p in existing_plates}

    merged: list[dict] = []

    # 1. Manual entries survive verbatim, regardless of the fresh run.
    merged.extend(dict(p) for p in existing_plates if p.get("reason") == MANUAL)

    # 2. Fresh choices (a manually-owned id keeps its manual entry, not a fresh one).
    for eid, choice in fresh_by_id.items():
        if eid in manual_ids:
            continue
        prior = existing_by_id.get(eid)
        if prior is None:
            merged.append(_plate(
                choice.page_id, choice.reason, choice.salience, "selected", revision,
                plate_id=choice.plate_id, anchor=choice.anchor, segment_index=choice.segment_index,
            ))
            continue
        status = prior["status"]
        added = prior["added_in_revision"]
        # rendered stays rendered (no re-render); everything else re-chosen keeps a live status.
        new_status = "rendered" if status == "rendered" else (
            status if status == "approved" else "selected"
        )
        merged.append(_plate(
            choice.page_id, choice.reason, choice.salience, new_status, added,
            plate_id=choice.plate_id, anchor=choice.anchor, segment_index=choice.segment_index,
        ))

    # 3. Existing non-manual plates that were not re-chosen.
    for prior in existing_plates:
        eid = _effective_id(prior)
        if prior.get("reason") == MANUAL or eid in fresh_by_id:
            continue
        status = prior["status"]
        if status == "rendered":
            merged.append(_plate(
                prior["page_id"], prior["reason"], prior["salience"], "retired",
                prior["added_in_revision"],
                plate_id=prior.get("plate_id"), anchor=prior.get("anchor"),
                segment_index=prior.get("segment_index"),
            ))
        elif status == "retired":
            merged.append(dict(prior))  # stays retired; files kept
        # else selected/approved never rendered → dropped (no pixels to preserve)

    merged.sort(key=_effective_id)
    return merged
