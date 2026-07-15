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
