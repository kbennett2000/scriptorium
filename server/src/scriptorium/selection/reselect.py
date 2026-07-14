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


def _plate(
    page_id: str, reason: str, salience: float, status: str, added_in_revision: int
) -> dict:
    return {
        "page_id": page_id,
        "reason": reason,
        "salience": salience,
        "status": status,
        "added_in_revision": added_in_revision,
    }


def reselect(
    fresh: list[PlateChoice], existing_plates: list[dict], *, revision: int
) -> list[dict]:
    """Merge a ``fresh`` selection into ``existing_plates`` for ``revision`` (DESIGN §8).

    ``revision`` is the new bundle revision (``current + 1``). Returns the merged plate list,
    sorted by ``page_id`` (== seq order).
    """
    fresh_by_id = {p.page_id: p for p in fresh}
    existing_by_id = {p["page_id"]: p for p in existing_plates}
    manual_ids = {p["page_id"] for p in existing_plates if p.get("reason") == MANUAL}

    merged: list[dict] = []

    # 1. Manual entries survive verbatim, regardless of the fresh run.
    merged.extend(dict(p) for p in existing_plates if p.get("reason") == MANUAL)

    # 2. Fresh choices (a manually-owned page id keeps its manual entry, not a fresh one).
    for page_id, choice in fresh_by_id.items():
        if page_id in manual_ids:
            continue
        prior = existing_by_id.get(page_id)
        if prior is None:
            merged.append(_plate(page_id, choice.reason, choice.salience, "selected", revision))
            continue
        status = prior["status"]
        added = prior["added_in_revision"]
        # rendered stays rendered (no re-render); everything else re-chosen keeps a live status.
        new_status = "rendered" if status == "rendered" else (
            status if status == "approved" else "selected"
        )
        merged.append(_plate(page_id, choice.reason, choice.salience, new_status, added))

    # 3. Existing non-manual plates that were not re-chosen.
    for prior in existing_plates:
        page_id = prior["page_id"]
        if prior.get("reason") == MANUAL or page_id in fresh_by_id:
            continue
        status = prior["status"]
        if status == "rendered":
            merged.append(
                _plate(page_id, prior["reason"], prior["salience"], "retired",
                       prior["added_in_revision"])
            )
        elif status == "retired":
            merged.append(dict(prior))  # stays retired; files kept
        # else selected/approved never rendered → dropped (no pixels to preserve)

    merged.sort(key=lambda p: p["page_id"])
    return merged
