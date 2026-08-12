"""Fake bake phases for S4 runner tests (DESIGN §7.3 mechanics, no real phase yet).

These are test doubles, deliberately living under ``tests/`` rather than the package so
no fake ships in production. Each writes a per-unit checkpoint artifact under
``work/{book_id}/{phase_name}/{unit}.json`` so ``unit_done`` (and therefore resume) is
exercised for real.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from scriptorium.bake.job import Job, JobState
from scriptorium.bake.phases.base import GpuUnavailable, Unit, UnitFailed


class _ArtifactPhase:
    """Shared checkpoint plumbing: an artifact per unit, read back by ``unit_done``."""

    name = "fake"
    from_state = JobState.INGESTED
    to_state = JobState.MENTIONS_RUNNING  # a legal adjacent edge from ingested
    is_gpu = False

    def _artifact(self, cfg, job: Job, unit: Unit) -> Path:
        return cfg.work_dir / job.book_id / self.name / f"{unit.id}.json"

    def unit_done(self, job: Job, cfg, unit: Unit) -> bool:
        path = self._artifact(cfg, job, unit)
        if not path.is_file():
            return False
        try:
            json.loads(path.read_text(encoding="utf-8"))
            return True
        except json.JSONDecodeError:
            return False

    def _write_artifact(self, cfg, job: Job, unit: Unit) -> None:
        path = self._artifact(cfg, job, unit)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"unit": unit.id}) + "\n", encoding="utf-8")


class FakeFlaky(_ArtifactPhase):
    """A non-GPU phase whose units fail a controlled number of times before succeeding.

    ``fail_counts[uid]`` = how many times unit ``uid`` raises :class:`UnitFailed` before
    it succeeds. A value larger than the retry ladder (e.g. 99) exhausts the retries and
    lands the unit in ``failed_units``; a value of 2 recovers on the third attempt.
    """

    name = "fake_flaky"

    def __init__(self, unit_ids: list[str], fail_counts: dict[str, int]) -> None:
        self.unit_ids = unit_ids
        self.fail_counts = fail_counts
        self.attempts: dict[str, int] = {}

    def units(self, job: Job, cfg) -> list[Unit]:
        return [Unit(id=uid) for uid in self.unit_ids]

    def run_unit(self, job: Job, cfg, unit: Unit) -> None:
        self.attempts[unit.id] = self.attempts.get(unit.id, 0) + 1
        if self.attempts[unit.id] <= self.fail_counts.get(unit.id, 0):
            raise UnitFailed(f"{unit.id} transient failure #{self.attempts[unit.id]}")
        self._write_artifact(cfg, job, unit)


class FakeGpuDown(_ArtifactPhase):
    """A GPU phase whose unit raises :class:`GpuUnavailable` while ``down`` is set.

    Flipping ``down`` to False models the GPU service coming back: the next attempt
    completes. ``from_state`` is a GPU running state so ``waiting_gpu`` is a legal edge.
    """

    name = "fake_gpu_down"
    from_state = JobState.PROMPTS_RUNNING
    to_state = JobState.PROMPTS_DRAFT
    is_gpu = True

    def __init__(self, down: bool = True) -> None:
        self.down = down
        self.run_calls = 0

    def units(self, job: Job, cfg) -> list[Unit]:
        return [Unit(id="p0001")]

    def run_unit(self, job: Job, cfg, unit: Unit) -> None:
        self.run_calls += 1
        if self.down:
            raise GpuUnavailable("gpu service 503")
        self._write_artifact(cfg, job, unit)


class CountingPhase(_ArtifactPhase):
    """Records every ``run_unit`` call and can simulate a hard kill mid-unit.

    When ``crash_on`` matches a unit, the call records the attempt then raises
    :class:`asyncio.CancelledError` **before** writing the artifact — modelling a process
    killed mid-unit (CancelledError is a BaseException, so the runner's bug-class
    ``except Exception`` does not catch it; it propagates like a real cancellation).
    """

    name = "fake_count"

    def __init__(self, unit_ids: list[str], crash_on: str | None = None) -> None:
        self.unit_ids = unit_ids
        self.crash_on = crash_on
        self.executed: list[str] = []

    def units(self, job: Job, cfg) -> list[Unit]:
        return [Unit(id=uid) for uid in self.unit_ids]

    def run_unit(self, job: Job, cfg, unit: Unit) -> None:
        self.executed.append(unit.id)
        if unit.id == self.crash_on:
            raise asyncio.CancelledError()
        self._write_artifact(cfg, job, unit)


class PausingPhase(_ArtifactPhase):
    """Simulates an operator pausing the job (via the API → disk) DURING the phase.

    While running ``pause_on``, it loads a SEPARATE Job instance and transitions it to PAUSED —
    exactly what the pause endpoint does — mimicking a pause that lands mid-phase without the
    in-memory worker knowing. Used to prove the runner re-checks and honors it instead of
    steamrolling it with the next per-unit save.
    """

    name = "fake_pausing"

    def __init__(self, unit_ids: list[str], pause_on: str) -> None:
        self.unit_ids = unit_ids
        self.pause_on = pause_on
        self.executed: list[str] = []

    def units(self, job: Job, cfg) -> list[Unit]:
        return [Unit(id=uid) for uid in self.unit_ids]

    def run_unit(self, job: Job, cfg, unit: Unit) -> None:
        self.executed.append(unit.id)
        self._write_artifact(cfg, job, unit)
        if unit.id == self.pause_on:
            from scriptorium.bake import job as jobmod

            other = jobmod.load(cfg, job.id)
            other.transition(JobState.PAUSED)
            other.save(cfg)
