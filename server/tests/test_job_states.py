"""Job state-machine tests (DESIGN §7.3): the transition table, legal and illegal.

The transition guard is structural — every legal edge is in ``LEGAL_TRANSITIONS`` and
anything else raises ``IllegalTransition``. These tests pin both directions, plus the
park/resume semantics for ``paused``/``waiting_gpu`` and dataclass round-trip.
"""

from __future__ import annotations

import pytest

from scriptorium.bake.job import (
    IllegalTransition,
    Job,
    JobState,
    can_transition,
)


def _job(state: str) -> Job:
    return Job(id="b", book_id="b", state=state)


LEGAL = [
    (JobState.CREATED, JobState.INGESTED),
    (JobState.INGESTED, JobState.MENTIONS_RUNNING),
    (JobState.MENTIONS_RUNNING, JobState.MENTIONS_DONE),
    (JobState.MENTIONS_DONE, JobState.CAST_RUNNING),
    (JobState.CAST_RUNNING, JobState.CAST_DONE),
    (JobState.CAST_DONE, JobState.LEDGER_RUNNING),
    (JobState.LEDGER_DONE, JobState.SELECTED),
    (JobState.PROMPTS_DRAFT, JobState.IN_REVIEW),
    (JobState.APPROVED, JobState.RENDERING),
    (JobState.RENDERING, JobState.PUBLISHED),
    # cross-cutting
    (JobState.MENTIONS_RUNNING, JobState.WAITING_GPU),
    (JobState.CAST_RUNNING, JobState.WAITING_GPU),  # P2 canonicalize parks (S5 deviation)
    (JobState.RENDERING, JobState.WAITING_GPU),
    (JobState.INGESTED, JobState.PAUSED),
    (JobState.RENDERING, JobState.FAILED),
]

ILLEGAL = [
    (JobState.CREATED, JobState.PUBLISHED),
    (JobState.INGESTED, JobState.RENDERING),
    (JobState.INGESTED, JobState.WAITING_GPU),  # not a GPU phase
    (JobState.PUBLISHED, JobState.INGESTED),  # terminal
    (JobState.PUBLISHED, JobState.FAILED),  # terminal
    (JobState.FAILED, JobState.INGESTED),  # terminal
    (JobState.MENTIONS_DONE, JobState.WAITING_GPU),  # done-state, not running
    (JobState.MENTIONS_DONE, JobState.CAST_DONE),  # cast_running now sits between them
]


@pytest.mark.parametrize(("src", "dst"), LEGAL)
def test_legal_transitions(src: str, dst: str) -> None:
    assert can_transition(src, dst)
    job = _job(src)
    job.transition(dst)
    assert job.state == dst


@pytest.mark.parametrize(("src", "dst"), ILLEGAL)
def test_illegal_transitions_raise(src: str, dst: str) -> None:
    assert not can_transition(src, dst)
    job = _job(src)
    with pytest.raises(IllegalTransition):
        job.transition(dst)
    assert job.state == src  # state unchanged on a rejected transition


def test_waiting_gpu_parks_prev_state_and_resumes() -> None:
    job = _job(JobState.MENTIONS_RUNNING)
    job.transition(JobState.WAITING_GPU)
    assert job.state == JobState.WAITING_GPU
    assert job.prev_state == JobState.MENTIONS_RUNNING
    # resume: the only legal non-fail destination is prev_state
    job.transition(JobState.MENTIONS_RUNNING)
    assert job.state == JobState.MENTIONS_RUNNING
    assert job.prev_state is None


def test_paused_parks_and_resumes_to_prev_only() -> None:
    job = _job(JobState.INGESTED)
    job.transition(JobState.PAUSED)
    assert job.prev_state == JobState.INGESTED
    # resuming anywhere but prev_state is illegal
    with pytest.raises(IllegalTransition):
        job.transition(JobState.RENDERING)
    job.transition(JobState.INGESTED)
    assert job.state == JobState.INGESTED
    assert job.prev_state is None


def test_can_fail_out_of_a_parked_state() -> None:
    job = _job(JobState.RENDERING)
    job.transition(JobState.WAITING_GPU)
    job.transition(JobState.FAILED)  # bug-class while parked
    assert job.state == JobState.FAILED


def test_dataclass_round_trip() -> None:
    job = Job(
        id="usr-abc",
        book_id="usr-abc",
        state=JobState.INGESTED,
        warnings=["chapters_undetected"],
        failed_units=[{"phase": "p", "unit": "u", "error": "e"}],
        started=True,
    )
    clone = Job.from_dict(job.to_dict())
    assert clone == job
