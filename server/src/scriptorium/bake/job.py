"""Bake job model + state machine (DESIGN §7.3).

A *job* is the durable record of one book's bake. There is exactly one job per book,
so ``job.id == book_id`` and it lives at ``jobs/{book_id}.json``. The record is
**internal runtime state**, not a distributed bundle format — it has no JSON Schema
(the schema'd artifacts are P0's ``work/{id}/pages/*`` + ``structure.json``, validated
by the paginator). ``jobs/`` is gitignored; nothing outside the server reads it.

The state machine is the §7.3 linear chain plus the cross-cutting states
``waiting_gpu`` / ``paused`` / ``failed``. ``transition`` is the single structural guard:
every legal edge lives in :data:`LEGAL_TRANSITIONS`, and anything else raises
:class:`IllegalTransition`. Entering ``paused``/``waiting_gpu`` stores the state to return
to in ``prev_state``; leaving them restores it.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ..config import Config


class JobState:
    """String constants for the §7.3 states (plain strings, JSON-friendly)."""

    CREATED = "created"
    INGESTED = "ingested"
    MENTIONS_RUNNING = "mentions_running"
    MENTIONS_DONE = "mentions_done"
    CAST_RUNNING = "cast_running"
    CAST_DONE = "cast_done"
    LEDGER_RUNNING = "ledger_running"
    LEDGER_DONE = "ledger_done"
    SELECTED = "selected"
    PROMPTS_RUNNING = "prompts_running"
    PROMPTS_DRAFT = "prompts_draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    # Optional portrait-review gate (ADR-0025). Portraits render first in their own GPU phase, then
    # the job rests at PORTRAITS_REVIEW for a human to eyeball/regenerate each portrait — but only
    # when the per-book ``portrait_review`` bake flag is set (else the runner auto-advances). Sits
    # between APPROVED and RENDERING so the approved portraits seed the page plates that follow.
    PORTRAITS_RENDERING = "portraits_rendering"
    PORTRAITS_REVIEW = "portraits_review"
    RENDERING = "rendering"
    RENDERED = "rendered"
    PUBLISHED = "published"
    # cross-cutting
    WAITING_GPU = "waiting_gpu"
    PAUSED = "paused"
    FAILED = "failed"
    # Per-user picture-set render (DESIGN §8, ADR-0014) — a self-contained side lifecycle,
    # deliberately OFF the book _CHAIN so it is never spliced into the book pipeline. A set job
    # renders in SET_RENDERING (a GPU state; parks on waiting_gpu) and ends at the distinct terminal
    # SET_DONE (reusing PUBLISHED would conflate set jobs with published books in /health + UI).
    SET_RENDERING = "set_rendering"
    SET_DONE = "set_done"


# The forward chain (DESIGN §7.3). ``LEGAL_TRANSITIONS[a]`` = states reachable from ``a``
# along the pipeline. Cross-cutting edges (paused/waiting_gpu/failed) are added below.
_CHAIN: tuple[str, ...] = (
    JobState.CREATED,
    JobState.INGESTED,
    JobState.MENTIONS_RUNNING,
    JobState.MENTIONS_DONE,
    JobState.CAST_RUNNING,
    JobState.CAST_DONE,
    JobState.LEDGER_RUNNING,
    JobState.LEDGER_DONE,
    JobState.SELECTED,
    JobState.PROMPTS_RUNNING,
    JobState.PROMPTS_DRAFT,
    JobState.IN_REVIEW,
    JobState.APPROVED,
    JobState.PORTRAITS_RENDERING,
    JobState.PORTRAITS_REVIEW,
    JobState.RENDERING,
    JobState.RENDERED,
    JobState.PUBLISHED,
)

# Running states are the GPU-active phases; only these may fall back to ``waiting_gpu``
# (§7.4 — every GPU phase, on a 503-class, parks here and is retried each tick).
GPU_STATES: frozenset[str] = frozenset(
    {
        JobState.MENTIONS_RUNNING,
        JobState.CAST_RUNNING,
        JobState.LEDGER_RUNNING,
        JobState.PROMPTS_RUNNING,
        JobState.PORTRAITS_RENDERING,
        JobState.RENDERING,
        JobState.SET_RENDERING,
    }
)

# Terminal states: nothing advances out of them.
TERMINAL_STATES: frozenset[str] = frozenset(
    {JobState.PUBLISHED, JobState.FAILED, JobState.SET_DONE}
)

# States a running worker can be actively processing (i.e. can be paused / failed / park
# for GPU). Everything on the chain except the terminal PUBLISHED, plus waiting_gpu itself.
_ACTIVE: frozenset[str] = frozenset(_CHAIN) - {JobState.PUBLISHED}


def _build_transitions() -> dict[str, set[str]]:
    table: dict[str, set[str]] = {s: set() for s in _CHAIN}
    table[JobState.WAITING_GPU] = set()
    table[JobState.PAUSED] = set()
    table[JobState.FAILED] = set()
    # Picture-set render side lifecycle (ADR-0014): seed its keys HERE, before the GPU_STATES pass
    # below adds SET_RENDERING -> waiting_gpu (and waiting_gpu -> SET_RENDERING). Its only outcomes
    # are SET_DONE (terminal) or FAILED (bug-class); SET_DONE has no outbound edges.
    table[JobState.SET_RENDERING] = {JobState.SET_DONE, JobState.FAILED}
    table[JobState.SET_DONE] = set()

    # Forward chain edges.
    for a, b in zip(_CHAIN, _CHAIN[1:], strict=False):
        table[a].add(b)

    # Any active (non-terminal) state may be paused by a human or fail (bug-class).
    for s in _ACTIVE:
        table[s].add(JobState.PAUSED)
        table[s].add(JobState.FAILED)

    # GPU phases may park on 503-class; waiting_gpu returns to any GPU running state and
    # may itself be paused / failed.
    for s in GPU_STATES:
        table[s].add(JobState.WAITING_GPU)
    table[JobState.WAITING_GPU] |= set(GPU_STATES) | {JobState.PAUSED, JobState.FAILED}

    # paused returns to any active state (resume restores prev_state, validated here).
    table[JobState.PAUSED] |= set(_ACTIVE) | {JobState.FAILED}
    return table


LEGAL_TRANSITIONS: dict[str, set[str]] = _build_transitions()


class IllegalTransition(ValueError):
    """Raised when a state transition is not permitted by :data:`LEGAL_TRANSITIONS`."""


def can_transition(src: str, dst: str) -> bool:
    """True iff ``src -> dst`` is a legal edge."""
    return dst in LEGAL_TRANSITIONS.get(src, set())


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class Job:
    """The durable record of one book's bake (see module docstring)."""

    id: str
    book_id: str
    state: str
    source: dict = field(default_factory=dict)
    bake_config: dict = field(default_factory=dict)
    title: str | None = None
    warnings: list[str] = field(default_factory=list)
    # Per-page TTS ``meta.warnings`` from prompt derivation (P5), keyed by page_id. Surfaced by
    # the review gate (S9). Schema-free runtime state, like the rest of the job record.
    prompt_warnings: dict[str, list[str]] = field(default_factory=dict)
    # Set True by the S9 demo render stub (P7) when it writes FakeImagegen placeholder pixels, so
    # S10's real render (and the post-render UI) know the plates are placeholders, not final art.
    render_stub: bool = False
    failed_units: list[dict] = field(default_factory=list)
    prev_state: str | None = None
    started: bool = False
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    # --- state machine ------------------------------------------------------

    def transition(self, dst: str) -> None:
        """Move to ``dst`` if legal, else raise :class:`IllegalTransition`.

        Entering ``paused``/``waiting_gpu`` records the current state in ``prev_state``;
        leaving them (the runner/resume path) clears it. Resuming out of ``paused`` must
        target the stored ``prev_state`` — any other destination is illegal.
        """
        if self.state in (JobState.PAUSED, JobState.WAITING_GPU):
            # Leaving a parked state: the only legal non-fail destination is prev_state.
            if dst != JobState.FAILED and dst != self.prev_state:
                raise IllegalTransition(
                    f"can only resume {self.state} to prev_state "
                    f"{self.prev_state!r}, not {dst!r}"
                )
            if not can_transition(self.state, dst):
                raise IllegalTransition(f"{self.state} -> {dst} not permitted")
            self.state = dst
            self.prev_state = None
            self.updated_at = _now()
            return

        if not can_transition(self.state, dst):
            raise IllegalTransition(f"{self.state} -> {dst} not permitted")
        if dst in (JobState.PAUSED, JobState.WAITING_GPU):
            self.prev_state = self.state
        self.state = dst
        self.updated_at = _now()

    # --- persistence --------------------------------------------------------

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Job:
        return cls(**data)

    def save(self, cfg: Config) -> Path:
        """Persist atomically to ``jobs/{id}.json`` (tmp file + ``os.replace``).

        The atomic replace is load-bearing for the kill-test: a server killed mid-write
        can never leave a half-written, unparseable job record.
        """
        self.updated_at = _now()
        path = job_path(cfg, self.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, path)
        return path


def job_path(cfg: Config, job_id: str) -> Path:
    return cfg.jobs_dir / f"{job_id}.json"


def load(cfg: Config, job_id: str) -> Job | None:
    """Load one job by id, or ``None`` if it does not exist."""
    path = job_path(cfg, job_id)
    if not path.is_file():
        return None
    return Job.from_dict(json.loads(path.read_text(encoding="utf-8")))


def list_jobs(cfg: Config) -> list[Job]:
    """All jobs on disk, oldest ``created_at`` first (the runner's queue order)."""
    jobs: list[Job] = []
    if not cfg.jobs_dir.is_dir():
        return jobs
    for path in cfg.jobs_dir.glob("*.json"):
        try:
            jobs.append(Job.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except (json.JSONDecodeError, TypeError):
            continue  # skip unreadable/foreign files; /health reports them separately
    jobs.sort(key=lambda j: j.created_at)
    return jobs
