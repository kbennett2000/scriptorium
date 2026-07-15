"""Runner mechanics (DESIGN §7.3/§7.4/§11.2), proven with fake phases.

Covered: the retry ladder (recover vs. exhaust→failed_units), the ``waiting_gpu`` park/
resume cycle both via the GPU health gate and via a mid-phase ``GpuUnavailable``, the WoL
helper's guard, and the load-bearing kill/resume test (≤1 in-flight unit lost).

Async runner coroutines are driven with ``asyncio.run`` so no pytest-asyncio dep is needed.
"""

from __future__ import annotations

import asyncio

import pytest

from fake_phases import CountingPhase, FakeFlaky, FakeGpuDown
from scriptorium.bake import job as jobmod
from scriptorium.bake import runner as runnermod
from scriptorium.bake.job import Job, JobState
from scriptorium.bake.runner import Runner, wake_gpu
from scriptorium.config import Config


def _cfg(tmp_path, **overrides) -> Config:
    base = dict(
        data_dir=tmp_path,
        port=8720,
        tts_url="http://tts.test:8712",
        imagegen_url=None,
        gpu_mac=None,
        gpu_wol_enabled=False,
        runner_tick_s=1,
        shared_dir=tmp_path,
    )
    base.update(overrides)
    return Config(**base)


async def _noop_sleep(_seconds: float) -> None:
    return None


def _started_job(cfg: Config, state: str) -> Job:
    job = Job(id="b", book_id="b", state=state, started=True)
    job.save(cfg)
    return job


# --- retry ladder -----------------------------------------------------------


def test_flaky_recovers_and_records_failed_units(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    job = _started_job(cfg, JobState.INGESTED)
    # u1 clean; u2 recovers on the 3rd try; u3 always fails (99 > ladder).
    phase = FakeFlaky(["u1", "u2", "u3"], fail_counts={"u2": 2, "u3": 99})

    delays: list[float] = []

    async def rec_sleep(seconds: float) -> None:
        delays.append(seconds)

    runner = Runner(cfg, [phase], sleep=rec_sleep)
    asyncio.run(runner.advance_job(job))

    # Phase completed despite the failures.
    assert job.state == JobState.MENTIONS_RUNNING
    # Only the always-failing unit is recorded; the recovered one is not.
    assert [f["unit"] for f in job.failed_units] == ["u3"]
    assert job.failed_units[0]["phase"] == "fake_flaky"
    # u2 recovered on attempt 3; u3 attempted the full 1 + 3 ladder.
    assert phase.attempts["u2"] == 3
    assert phase.attempts["u3"] == 4
    # Ladder delays: u2 slept 10,60; u3 slept 10,60,300.
    assert delays == [10, 60, 10, 60, 300]
    # The recovered unit left a checkpoint; the failed one did not.
    assert phase.unit_done(job, cfg, next(u for u in phase.units(job, cfg) if u.id == "u2"))
    assert not phase.unit_done(job, cfg, next(u for u in phase.units(job, cfg) if u.id == "u3"))


# --- waiting_gpu via a mid-phase GpuUnavailable -----------------------------


def test_gpu_unavailable_parks_then_resumes_when_back(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _started_job(cfg, JobState.PROMPTS_RUNNING)
    phase = FakeGpuDown(down=True)
    wake_calls: list[Config] = []

    async def gate_up(_cfg: Config) -> bool:
        return True

    runner = Runner(
        cfg, [phase], sleep=_noop_sleep, wake=wake_calls.append, gpu_gate=gate_up
    )

    asyncio.run(runner.tick())  # gate passes, run_unit raises → waiting_gpu
    parked = jobmod.load(cfg, "b")
    assert parked.state == JobState.WAITING_GPU
    assert parked.prev_state == JobState.PROMPTS_RUNNING
    assert len(wake_calls) == 1

    phase.down = False  # service back
    asyncio.run(runner.tick())  # resume → run_unit succeeds → prompts_draft
    done = jobmod.load(cfg, "b")
    assert done.state == JobState.PROMPTS_DRAFT
    assert len(wake_calls) == 2  # WoL sent on entry each attempt (§7.4)


# --- waiting_gpu via the health gate ----------------------------------------


def test_gpu_gate_down_parks_before_running_units(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _started_job(cfg, JobState.PROMPTS_RUNNING)
    phase = FakeGpuDown(down=False)  # unit would succeed; the gate blocks entry
    gate_results = iter([False, True])
    wake_calls: list[Config] = []

    async def gate(_cfg: Config) -> bool:
        return next(gate_results)

    runner = Runner(
        cfg, [phase], sleep=_noop_sleep, wake=wake_calls.append, gpu_gate=gate
    )

    asyncio.run(runner.tick())  # gate False → parked, unit never ran
    assert jobmod.load(cfg, "b").state == JobState.WAITING_GPU
    assert phase.run_calls == 0

    asyncio.run(runner.tick())  # gate True → resume, unit runs → advance
    assert jobmod.load(cfg, "b").state == JobState.PROMPTS_DRAFT
    assert phase.run_calls == 1
    assert len(wake_calls) == 2


# --- scheduling: a review-gated job must not starve newer jobs --------------


def test_review_gated_job_does_not_starve_newer_jobs(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    # Older job parked at the review gate: prompts_draft has no worker phase (the human
    # approve endpoint advances it), so the runner has nothing to run for it.
    parked = Job(
        id="parked", book_id="parked", state=JobState.PROMPTS_DRAFT,
        started=True, created_at="2020-01-01T00:00:00+00:00",
    )
    parked.save(cfg)
    # Newer job ready to run from ingested (a phase IS registered for ingested).
    fresh = Job(
        id="fresh", book_id="fresh", state=JobState.INGESTED,
        started=True, created_at="2020-01-02T00:00:00+00:00",
    )
    fresh.save(cfg)

    phase = CountingPhase(["u1"])  # from_state=INGESTED -> to_state=MENTIONS_RUNNING
    runner = Runner(cfg, [phase], sleep=_noop_sleep)
    asyncio.run(runner.tick())

    # The parked job is left alone; the fresh job advanced (it was NOT starved behind it).
    assert jobmod.load(cfg, "parked").state == JobState.PROMPTS_DRAFT
    assert phase.executed == ["u1"]
    assert jobmod.load(cfg, "fresh").state == JobState.MENTIONS_RUNNING


# --- GPU hand-off: free the image GPU before a text phase (single-GPU sequencing) ---------


def test_text_gpu_phase_frees_the_image_gpu_first(tmp_path) -> None:
    # A text/LLM GPU phase must release the image GPU (ComfyUI) before running so the LLM gets
    # the card. FakeGpuDown is a text GPU phase (no gpu_kind → "text").
    cfg = _cfg(tmp_path)
    _started_job(cfg, JobState.PROMPTS_RUNNING)
    freed: list[Config] = []

    async def gate_up(_c: Config) -> bool:
        return True

    async def spy_free(c: Config) -> None:
        freed.append(c)

    runner = Runner(cfg, [FakeGpuDown(down=False)], sleep=_noop_sleep,
                    gpu_gate=gate_up, free_image_gpu=spy_free)
    asyncio.run(runner.tick())

    assert len(freed) == 1  # freed the image GPU exactly once, before the units
    assert jobmod.load(cfg, "b").state == JobState.PROMPTS_DRAFT


def test_image_gpu_phase_does_not_free_the_card_it_needs(tmp_path) -> None:
    # A render phase (gpu_kind="image") needs SDXL resident, so the runner must NOT free it.
    cfg = _cfg(tmp_path)
    _started_job(cfg, JobState.PROMPTS_RUNNING)
    phase = FakeGpuDown(down=False)
    phase.gpu_kind = "image"  # mark as a render-style phase
    freed: list[Config] = []

    async def gate_up(_c: Config) -> bool:
        return True

    async def spy_free(c: Config) -> None:
        freed.append(c)

    runner = Runner(cfg, [phase], sleep=_noop_sleep, gpu_gate=gate_up, free_image_gpu=spy_free)
    asyncio.run(runner.tick())

    assert freed == []  # the image GPU was left loaded


# --- WoL helper -------------------------------------------------------------


def test_wol_sends_only_when_enabled(tmp_path, monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(argv)

    monkeypatch.setattr(runnermod.subprocess, "run", fake_run)

    wake_gpu(_cfg(tmp_path, gpu_wol_enabled=True, gpu_mac="AA:BB:CC:DD:EE:FF"))
    assert calls == [["wakeonlan", "AA:BB:CC:DD:EE:FF"]]

    calls.clear()
    wake_gpu(_cfg(tmp_path, gpu_wol_enabled=False, gpu_mac="AA:BB:CC:DD:EE:FF"))
    wake_gpu(_cfg(tmp_path, gpu_wol_enabled=True, gpu_mac=None))
    assert calls == []


# --- kill / resume (load-bearing) -------------------------------------------


def test_kill_mid_unit_resumes_losing_at_most_one_unit(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _started_job(cfg, JobState.INGESTED)
    units = ["u0", "u1", "u2", "u3", "u4"]

    # First runner is "killed" mid-u3 (CancelledError, uncaught by bug-class handling).
    phase1 = CountingPhase(units, crash_on="u3")
    runner1 = Runner(cfg, [phase1], sleep=_noop_sleep)
    job = jobmod.load(cfg, "b")
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(runner1.advance_job(job))

    # u0..u2 completed + persisted; u3 attempted but its artifact never landed.
    assert phase1.executed == ["u0", "u1", "u2", "u3"]
    reloaded = jobmod.load(cfg, "b")
    assert reloaded.state == JobState.INGESTED  # phase never reached to_state
    assert reloaded.failed_units == []

    # Restart: a fresh phase + runner over the same on-disk job.
    phase2 = CountingPhase(units, crash_on=None)
    runner2 = Runner(cfg, [phase2], sleep=_noop_sleep)
    asyncio.run(runner2.advance_job(reloaded))

    assert reloaded.state == JobState.MENTIONS_RUNNING  # phase now completes
    # Completed units were skipped on resume; only the in-flight unit is redone.
    assert "u0" not in phase2.executed
    assert "u1" not in phase2.executed
    assert "u2" not in phase2.executed
    assert phase2.executed == ["u3", "u4"]
    overlap = set(phase1.executed) & set(phase2.executed)
    assert len(overlap) <= 1  # ≤ one unit of work lost across the kill
