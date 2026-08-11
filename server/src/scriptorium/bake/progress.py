"""Read-time bake-progress derivation for the admin status endpoint.

The job record carries no per-phase counters (see ``job.py``); instead the runner writes one
artifact per finished unit, so ``done`` is a cheap directory count and ``total`` is the phase's
unit universe (pages, majors, plates). This module computes that per the job's current state so the
admin UI can show a real "398 / 613" bar and tell a stall from slow progress — without persisting
anything or parsing every artifact.

Pure and cheap: only ``Path.glob`` counts plus at most two small single-file reads. A missing dir
globs to zero; any read error degrades ``total`` to ``None`` (the UI then shows a bare count).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .job import Job, JobState

# States where the runner is NOT expected to be actively advancing on its own: not started, waiting
# on a human (review gate), parked, finished, or failed. Every other chain state — including the
# transient ``*_done``/``selected``/``ingested`` hops the runner clears at once — IS expected to
# progress, so a lack of movement there is a real stall worth surfacing. ``waiting_gpu`` is excluded
# because it has its own dedicated banner.
_NOT_EXPECTING: frozenset[str] = frozenset({
    JobState.CREATED,
    JobState.PROMPTS_DRAFT,
    JobState.IN_REVIEW,
    JobState.PORTRAITS_REVIEW,  # optional portrait gate (ADR-0025): waiting on a human
    JobState.PAUSED,
    JobState.PUBLISHED,
    JobState.FAILED,
    JobState.WAITING_GPU,
    JobState.SET_DONE,
})


def _count(directory: Path, pattern: str) -> int:
    """Number of files matching ``pattern`` in ``directory`` (0 if the dir is absent)."""
    return sum(1 for _ in directory.glob(pattern))


def _majors_total(cast_groups: Path) -> int | None:
    try:
        groups = json.loads(cast_groups.read_text(encoding="utf-8"))
        return sum(1 for g in groups if g.get("major"))
    except (OSError, ValueError):
        return None


def _prompts_total(selection: Path, cast_json: Path) -> int | None:
    """Plates P5 will prompt: the selection's page plates + one portrait per major + a cover."""
    try:
        plates = json.loads(selection.read_text(encoding="utf-8")).get("plates", [])
        total = len(plates) + 1  # + cover
    except (OSError, ValueError):
        return None
    try:
        cast = json.loads(cast_json.read_text(encoding="utf-8")).get("characters", [])
        total += sum(1 for c in cast if c.get("major"))
    except (OSError, ValueError):
        pass  # portraits unknown → count is a lower bound; the bar just under-fills slightly
    return total


def phase_progress(job: Job, cfg: Any) -> dict[str, int | None]:
    """`{units_done, units_total}` for the job's current phase (either may be ``None``).

    ``units_total`` is ``None`` for the CPU/enter/single-unit/resting phases that have no meaningful
    fraction (the UI then shows no bar). ``units_done`` is clamped to ``units_total``.
    """
    work = cfg.work_dir / job.book_id
    state = job.state

    done: int | None = None
    total: int | None = None
    if state == JobState.MENTIONS_RUNNING:
        done, total = _count(work / "mentions", "*.json"), _count(work / "pages", "*.json")
    elif state == JobState.CAST_RUNNING:
        done = _count(work / "cast" / "canon", "*.json")
        total = _majors_total(work / "cast" / "groups.json")
    elif state == JobState.LEDGER_RUNNING:
        done, total = _count(work / "ledgers", "*.json"), _count(work / "pages", "*.json")
    elif state == JobState.PROMPTS_RUNNING:
        done = _count(work / "prompts", "*.json")
        total = _prompts_total(work / "selection.json", work / "cast.json")
    elif state == JobState.PORTRAITS_RENDERING:
        done = _count(work / "images" / "web" / "portraits", "*.webp")
        total = _count(work / "prompts", "portrait-*.json")
    elif state in (JobState.RENDERING, JobState.SET_RENDERING):
        done = _count(work / "images" / "web" / "plates", "*.webp")
        total = _count(work / "prompts", "*.json")

    if done is not None and total is not None:
        done = min(done, total)
    return {"units_done": done, "units_total": total}


def status_extras(job: Job, cfg: Any) -> dict[str, Any]:
    """Progress + liveness fields to merge onto ``job.to_dict()`` for the admin status poll."""
    now = datetime.now(UTC)
    try:
        since = (now - datetime.fromisoformat(job.updated_at)).total_seconds()
    except (ValueError, TypeError):
        since = 0.0
    return {
        "progress": phase_progress(job, cfg),
        "server_now": now.isoformat(),
        "seconds_since_activity": max(0.0, since),
        "expecting_progress": bool(job.started) and job.state not in _NOT_EXPECTING,
        # True when the server runs fully hands-off (ADR-0020 + ADR-0015): a new book starts itself
        # and clears the review gate on its own, so the UI can tell the owner no click is coming.
        "unattended": bool(
            getattr(cfg, "auto_start", False) and getattr(cfg, "auto_approve", False)
        ),
    }
