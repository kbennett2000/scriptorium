"""Bounded parallel fan-out of render units (ADR-0038).

The runner is documented as structurally enforcing GPU exclusivity by having exactly
one worker (§7.4). That reasoning holds while rendering happens on *the* GPU. Once a
plate renders on a pool of remote workers there is no local card to be exclusive
about, so plate units may overlap — but nothing else about the runner's contract may
change with them.

These tests pin the contract rather than the speedup:

- `__unload__` still runs alone and first, so TTS is unloaded before any plate draws.
- Every plate renders exactly once, and `unit_done` still skips finished ones.
- One plate's `UnitFailed` retries **that plate** and does not re-render its
  neighbours — the ladder is per unit, not per batch.
- `GpuUnavailable` still parks the job on `waiting_gpu`.
- At concurrency 1 the batching is a no-op, which is what every local deployment gets.

Concurrency itself is asserted by observing overlap directly (a counter of in-flight
renders), not by timing, so the tests are deterministic.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from scriptorium.bake.phases.base import GpuUnavailable, Unit, UnitFailed
from scriptorium.bake.runner import Runner, _batches

# --- the batching rule, in isolation ----------------------------------------


def _u(name: str, parallel: bool = False) -> Unit:
    return Unit(id=name, parallel=parallel)


def test_width_one_is_one_unit_per_batch() -> None:
    """The pre-fan-out behaviour, and what every local deployment runs."""
    units = [_u("__unload__"), _u("a", True), _u("b", True), _u("c", True)]
    assert _batches(units, 1) == [[units[0]], [units[1]], [units[2]], [units[3]]]


def test_sequential_units_never_join_a_batch() -> None:
    """__unload__ must complete alone and before any plate (§7.4)."""
    units = [_u("__unload__"), _u("a", True), _u("b", True)]
    batches = _batches(units, 4)
    assert [[x.id for x in b] for b in batches] == [["__unload__"], ["a", "b"]]


def test_parallel_runs_are_chunked_to_width_and_keep_order() -> None:
    units = [_u("__unload__")] + [_u(str(i), True) for i in range(5)]
    batches = _batches(units, 2)
    assert [[x.id for x in b] for b in batches] == [
        ["__unload__"], ["0", "1"], ["2", "3"], ["4"],
    ]


def test_a_sequential_unit_between_parallel_runs_splits_them() -> None:
    units = [_u("a", True), _u("gate"), _u("b", True), _u("c", True)]
    assert [[x.id for x in b] for b in _batches(units, 4)] == [["a"], ["gate"], ["b", "c"]]


# --- the runner, driving a phase --------------------------------------------


class _Job:
    """Just enough Job for advance_job: a state machine that records transitions."""

    def __init__(self) -> None:
        self.id = "bk"
        self.state = "rendering"
        self.prev_state = None
        self.failed_units: list[dict] = []
        self.saves = 0
        self.transitions: list[str] = []

    def transition(self, to: str) -> None:
        self.transitions.append(to)
        self.state = to

    def save(self, cfg: object) -> None:
        self.saves += 1


class _Phase:
    """A render-shaped phase: a sequential gate unit, then N parallel plate units."""

    name = "p7_render"
    from_state = "rendering"
    to_state = "rendered"
    is_gpu = False  # skip the GPU gate; it is not what these tests are about

    def __init__(self, plates: list[str], *, done: set[str] | None = None,
                 fail: dict[str, int] | None = None, raise_gpu: str | None = None) -> None:
        self._plates = plates
        self._done = done or set()
        self._fail = dict(fail or {})       # plate -> how many times to fail first
        self._raise_gpu = raise_gpu
        self.calls: list[str] = []
        self.inflight = 0
        self.max_inflight = 0

    def units(self, job: object, cfg: object) -> list[Unit]:
        return [Unit(id="__unload__")] + [Unit(id=p, parallel=True) for p in self._plates]

    def unit_done(self, job: object, cfg: object, unit: Unit) -> bool:
        return unit.id in self._done

    async def run_unit(self, job: object, cfg: object, unit: Unit) -> None:
        self.inflight += 1
        self.max_inflight = max(self.max_inflight, self.inflight)
        try:
            await asyncio.sleep(0)  # a real await, so overlap is observable
            self.calls.append(unit.id)
            if unit.id == self._raise_gpu:
                raise GpuUnavailable(f"{unit.id} says the pool is down")
            if self._fail.get(unit.id, 0) > 0:
                self._fail[unit.id] -= 1
                raise UnitFailed(f"{unit.id} transient")
        finally:
            self.inflight -= 1


def _runner(phase: _Phase, width: int, job: _Job, monkeypatch: pytest.MonkeyPatch) -> Runner:
    cfg = SimpleNamespace(effective_render_concurrency=width, runner_tick_s=5)
    async def _noop(_s: float) -> None:
        return None
    r = Runner(cfg, [phase], sleep=_noop)  # type: ignore[arg-type]
    # advance_job re-reads the persisted job to honour a mid-flight Pause; here the
    # job never changes underneath us, so hand back the same object.
    monkeypatch.setattr("scriptorium.bake.runner.jobmod.load", lambda cfg, jid: job)
    return r


def test_every_plate_renders_exactly_once(monkeypatch: pytest.MonkeyPatch) -> None:
    plates = [f"{i:04d}" for i in range(9)]
    phase, job = _Phase(plates), _Job()
    asyncio.run(_runner(phase, 4, job, monkeypatch).advance_job(job))
    assert phase.calls[0] == "__unload__"
    assert sorted(phase.calls[1:]) == sorted(plates)
    assert len(phase.calls) == len(plates) + 1
    assert job.transitions[-1] == "rendered"


def test_plates_actually_overlap_and_respect_the_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plates = [f"{i:04d}" for i in range(9)]
    phase, job = _Phase(plates), _Job()
    asyncio.run(_runner(phase, 4, job, monkeypatch).advance_job(job))
    assert phase.max_inflight > 1, "plates did not overlap"
    assert phase.max_inflight <= 4, "the concurrency bound was exceeded"


def test_unload_never_overlaps_a_plate(monkeypatch: pytest.MonkeyPatch) -> None:
    """The §7.4 invariant: TTS is unloaded before SDXL is asked for anything."""
    plates = [f"{i:04d}" for i in range(6)]

    class _Strict(_Phase):
        async def run_unit(self, job: object, cfg: object, unit: Unit) -> None:
            if self.inflight and unit.id == "__unload__":
                raise AssertionError("unload ran alongside a plate")
            if unit.id != "__unload__" and "__unload__" not in self.calls:
                raise AssertionError("a plate ran before unload")
            await super().run_unit(job, cfg, unit)

    phase, job = _Strict(plates), _Job()
    asyncio.run(_runner(phase, 4, job, monkeypatch).advance_job(job))
    assert job.transitions[-1] == "rendered"


def test_concurrency_one_is_call_for_call_the_old_behaviour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plates = [f"{i:04d}" for i in range(5)]
    phase, job = _Phase(plates), _Job()
    asyncio.run(_runner(phase, 1, job, monkeypatch).advance_job(job))
    assert phase.calls == ["__unload__"] + plates      # strict order, not a set
    assert phase.max_inflight == 1                      # never overlapped
    # One save per unit (unload + 5 plates), plus one for the closing transition —
    # the resumability invariant, unchanged.
    assert job.saves == len(plates) + 2


def test_finished_plates_are_skipped_on_resume(monkeypatch: pytest.MonkeyPatch) -> None:
    plates = [f"{i:04d}" for i in range(6)]
    phase = _Phase(plates, done={"0000", "0003"})
    job = _Job()
    asyncio.run(_runner(phase, 4, job, monkeypatch).advance_job(job))
    assert "0000" not in phase.calls and "0003" not in phase.calls
    assert sorted(phase.calls[1:]) == ["0001", "0002", "0004", "0005"]


def test_one_plates_failure_retries_only_that_plate(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ladder is per unit. A batch-level retry would re-render paid-for neighbours."""
    plates = ["0000", "0001", "0002", "0003"]
    phase = _Phase(plates, fail={"0002": 2})   # fails twice, then succeeds
    job = _Job()
    asyncio.run(_runner(phase, 4, job, monkeypatch).advance_job(job))
    assert phase.calls.count("0002") == 3      # two failures, then the success
    for other in ("0000", "0001", "0003"):
        assert phase.calls.count(other) == 1, f"{other} was re-rendered"
    assert job.failed_units == []
    assert job.transitions[-1] == "rendered"


def test_a_plate_that_exhausts_the_ladder_is_recorded_and_the_phase_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plates = ["0000", "0001", "0002"]
    phase = _Phase(plates, fail={"0001": 99})
    job = _Job()
    asyncio.run(_runner(phase, 4, job, monkeypatch).advance_job(job))
    assert [f["unit"] for f in job.failed_units] == ["0001"]
    assert phase.calls.count("0000") == 1 and phase.calls.count("0002") == 1
    assert job.transitions[-1] == "rendered"


def test_gpu_unavailable_in_a_batch_parks_the_job(monkeypatch: pytest.MonkeyPatch) -> None:
    plates = ["0000", "0001", "0002", "0003"]
    phase = _Phase(plates, raise_gpu="0002")
    job = _Job()
    asyncio.run(_runner(phase, 4, job, monkeypatch).advance_job(job))
    assert job.state == "waiting_gpu"
    assert "rendered" not in job.transitions


def test_siblings_are_not_cancelled_when_one_plate_parks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A render already in flight is already paid for; cancelling it wastes it and
    leaves no artifact for unit_done to skip on resume."""
    plates = ["0000", "0001", "0002", "0003"]
    phase = _Phase(plates, raise_gpu="0000")
    job = _Job()
    asyncio.run(_runner(phase, 4, job, monkeypatch).advance_job(job))
    assert job.state == "waiting_gpu"
    for sibling in ("0001", "0002", "0003"):
        assert sibling in phase.calls, f"{sibling} was cancelled mid-batch"
