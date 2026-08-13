"""Shared shot-list approval logic (DESIGN §11.1, invariant #4 — "no plate rendered before
approval").

The core of the review gate, extracted so two callers apply *identical* rules:

- the human review endpoint (:func:`.review_api.approve`), and
- the optional auto-approve runner path (``AUTO_APPROVE``, ADR-0015).

Auto-approve is the same gate with the click automated, **not a bypass**: it runs the exact
missing-prompt guard and the same ``prompts_draft -> in_review -> approved`` transition. The
guard (a renderable plate with no prompt refuses approval) is what keeps a half-derived shot list
from ever reaching the renderer.
"""

from __future__ import annotations

import json

from .. import schemas
from ..config import Config
from .job import Job, JobState

# States in which the review artifacts exist and approval is legal (§11.1).
_REVIEW_STATES = (JobState.PROMPTS_DRAFT, JobState.IN_REVIEW)


class ApprovalBlocked(Exception):
    """Approval refused because renderable plates lack prompt artifacts.

    Carries the offending ``page_ids`` so the caller can surface them (the endpoint returns
    them in a 422; the auto-approve runner leaves the job parked for a human instead).
    """

    def __init__(self, page_ids: list[str]) -> None:
        super().__init__(f"selected plates missing prompts: {page_ids}")
        self.page_ids = page_ids


class CastApprovalBlocked(Exception):
    """Cast approval refused because a major character has no description yet (ADR-0032).

    Carries the offending character ``slugs`` (a major with an empty ``one_line`` or
    ``visual_description``) — the scene prompts derived after this gate depend on them, so
    approving with a blank major would defeat the gate. Same surfacing contract as
    :class:`ApprovalBlocked`: 422 from the endpoint, park-for-human on the auto path.
    """

    def __init__(self, slugs: list[str]) -> None:
        super().__init__(f"major characters missing descriptions: {slugs}")
        self.slugs = slugs


def approve_job(cfg: Config, job: Job) -> None:
    """Lock the shot list and advance ``job`` ``prompts_draft -> in_review -> approved``.

    Raises :class:`ValueError` if the job is not in a reviewable state (the endpoint maps this
    to 409) and :class:`ApprovalBlocked` if any plate that will render lacks a prompt (mapped to
    422). Neither transitions nor writes on failure — no partial approval.
    """
    if job.state not in _REVIEW_STATES:
        raise ValueError(f"cannot approve from {job.state}")

    book = cfg.work_dir / job.book_id
    sel_path = book / "selection.json"
    prompts_dir = book / "prompts"
    sel = json.loads(sel_path.read_text(encoding="utf-8"))

    # Every plate that will render (selected/approved, or any manual add) must already have a
    # prompt artifact — otherwise the renderer would have nothing to draw from.
    missing = sorted({
        p["page_id"] for p in sel["plates"]
        if (p["status"] in ("selected", "approved") or p.get("reason") == "manual")
        and not (prompts_dir / f"{p['page_id']}.json").is_file()
    })
    if missing:
        raise ApprovalBlocked(missing)

    for plate in sel["plates"]:
        if plate["status"] == "selected":
            plate["status"] = "approved"
    schemas.validate("selection", sel)
    sel_path.parent.mkdir(parents=True, exist_ok=True)
    sel_path.write_text(json.dumps(sel, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if job.state == JobState.PROMPTS_DRAFT:
        job.transition(JobState.IN_REVIEW)  # transient waypoint (see CYCLE-LOG S9a)
    job.transition(JobState.APPROVED)
    job.save(cfg)


def approve_cast(cfg: Config, job: Job) -> None:
    """Approve the cast descriptions and advance ``job`` ``cast_done -> cast_approved`` (ADR-0032).

    The gate before the scene prompts are derived: the human has reviewed (and possibly edited)
    each character, and approving lets P3→P5 run against the approved cast. Mirrors
    :func:`approve_job` — a guard, not a bypass — and is reused by the ``AUTO_APPROVE`` runner path.

    Raises :class:`ValueError` if the job is not parked at the cast gate (endpoint maps to 409) and
    :class:`CastApprovalBlocked` if any ``major`` character still lacks a ``one_line`` or
    ``visual_description`` (mapped to 422). Neither transitions nor writes on failure. No artifact
    write is needed — cast edits already persisted ``cast.json``; this only advances the state.
    """
    if job.state != JobState.CAST_DONE:
        raise ValueError(f"cannot approve cast from {job.state}")

    cast_path = cfg.work_dir / job.book_id / "cast.json"
    cast = json.loads(cast_path.read_text(encoding="utf-8"))

    # Every major (the characters that get a canonical description + portrait, and whose text feeds
    # the scene prompts) must have a non-empty one_line and visual_description before we derive from
    # them. Minors carry null descriptions by design and are not guarded.
    missing = sorted(
        c["slug"]
        for c in cast["characters"]
        if c.get("major")
        and not ((c.get("one_line") or "").strip() and (c.get("visual_description") or "").strip())
    )
    if missing:
        raise CastApprovalBlocked(missing)

    job.transition(JobState.CAST_APPROVED)
    job.save(cfg)


def approve_portraits(cfg: Config, job: Job) -> None:
    """Advance the optional portrait gate ``portraits_review -> rendering`` (ADR-0025).

    The human has eyeballed (and possibly edited/regenerated) the portraits; approving lets the
    page plates draw, seeded by the now-approved portrait PNGs. Unlike :func:`approve_job` there is
    no missing-artifact guard — the portraits already rendered to reach this state. Raises
    :class:`ValueError` (mapped to 409) if the job is not parked at the portrait gate.
    """
    if job.state != JobState.PORTRAITS_REVIEW:
        raise ValueError(f"cannot approve portraits from {job.state}")
    job.transition(JobState.RENDERING)
    job.save(cfg)
