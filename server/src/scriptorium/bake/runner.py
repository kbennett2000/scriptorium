"""Single-worker bake runner (DESIGN §7.3 / §7.4 / §11.2).

One asyncio worker, started with the app, loops: scan ``jobs/`` → pick the oldest
runnable job → advance it one phase → persist after every unit → sleep one tick. There
is no pool and no external queue (no Celery/Redis): the queue is a directory scan and the
single task **structurally** enforces GPU exclusivity (§7.4) — two GPU phases can never
interleave because there is only ever one worker.

Failure handling mirrors §7.3:
- :class:`~.phases.base.GpuUnavailable` → park in ``waiting_gpu``; every tick sends
  Wake-on-LAN (§7.4) and retries.
- :class:`~.phases.base.UnitFailed` → retry the unit 3× with a 10/60/300s backoff ladder,
  then record it in ``failed_units`` and continue the phase.
- any other exception (bug-class) → fail the whole job.

Persistence after every unit + artifact-based ``unit_done`` gives the resumability
invariant: a server killed mid-unit loses at most that one in-flight unit on restart.

``sleep`` / ``wake`` / ``gpu_gate`` are injectable so tests substitute no-op sleeps and
fake GPU gates without patching module globals.
"""

from __future__ import annotations

import asyncio
import inspect
import subprocess
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from ..config import Config
from . import job as jobmod
from .approve import ApprovalBlocked, approve_job
from .job import Job, JobState
from .phases.base import GpuUnavailable, Phase, UnitFailed

# The unit-retry backoff ladder (§7.3): up to 3 retries after the first attempt.
RETRY_DELAYS: tuple[int, ...] = (10, 60, 300)

_GPU_PROBE_TIMEOUT_S = 15.0  # §7.4: poll health with a 15s timeout before proceeding


def wake_gpu(cfg: Config) -> None:
    """Send Wake-on-LAN to the GPU box, if enabled (§7.4).

    No-op unless ``GPU_WOL_ENABLED`` is set and a MAC is configured. ``check=False``:
    a missing ``wakeonlan`` binary must not crash the runner (the health poll is the
    real gate; WoL is best-effort).
    """
    if cfg.gpu_wol_enabled and cfg.gpu_mac:
        subprocess.run(["wakeonlan", cfg.gpu_mac], check=False)  # noqa: S603,S607


async def default_gpu_gate(cfg: Config) -> bool:
    """Poll the TTS service /health (§7.4). True iff reachable. Never raises."""
    url = cfg.tts_url
    if not url:
        return False
    endpoint = url.rstrip("/") + "/health"
    try:
        async with httpx.AsyncClient(timeout=_GPU_PROBE_TIMEOUT_S) as client:
            resp = await client.get(endpoint)
        return resp.is_success
    except Exception:
        return False


async def free_imagegen_gpu(cfg: Config) -> None:
    """Best-effort: ask the image service to release the GPU (ComfyUI VRAM) before a text phase.

    The mirror of P7's "unload TTS before render" (§7.4 / ADR-0009). On a single-GPU box the LLM
    and SDXL cannot both stay resident, so before a text/LLM GPU phase runs we free the card of the
    image model — otherwise the LLM spills onto the CPU (pegged CPU, idle GPU). ComfyUI's URL is
    discovered from imagegen-service ``/health`` (it advertises ``comfyuiUrl``), then we POST its
    ``/free``. Never raises: freeing is an optimization; on failure the phase still runs (as before,
    possibly on CPU if the card is full).
    """
    if not cfg.imagegen_url:
        return
    base = cfg.imagegen_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=_GPU_PROBE_TIMEOUT_S) as client:
            health = await client.get(base + "/health")
            comfy = health.json().get("comfyuiUrl") if health.is_success else None
            if not comfy:
                return
            await client.post(
                comfy.rstrip("/") + "/free",
                json={"unload_models": True, "free_memory": True},
            )
    except Exception:
        return


async def _maybe_await(value: Any) -> Any:
    """Await ``value`` if it is awaitable, else return it (phases may be sync or async)."""
    if inspect.isawaitable(value):
        return await value
    return value


class Runner:
    """The single bake worker. ``pipeline`` maps ``from_state`` → phase."""

    def __init__(
        self,
        cfg: Config,
        pipeline: list[Phase],
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        wake: Callable[[Config], None] = wake_gpu,
        gpu_gate: Callable[[Config], Awaitable[bool]] = default_gpu_gate,
        free_image_gpu: Callable[[Config], Awaitable[None]] = free_imagegen_gpu,
    ) -> None:
        self.cfg = cfg
        self._by_from: dict[str, Phase] = {p.from_state: p for p in pipeline}
        self._sleep = sleep
        self._wake = wake
        self._gpu_gate = gpu_gate
        self._free_image_gpu = free_image_gpu
        self._stop = False

    def phase_for(self, state: str) -> Phase | None:
        """The phase that advances a job out of ``state``, or ``None`` if none registered."""
        return self._by_from.get(state)

    async def _run_with_ladder(self, job: Job, phase: Phase, unit: Any) -> None:
        """Run one unit through the retry ladder (§7.3).

        Recovers a unit that fails transiently; on exhausting the 3 retries records it in
        ``failed_units`` and returns so the phase continues. ``GpuUnavailable`` and
        bug-class exceptions propagate to the caller.
        """
        attempt = 0
        while True:
            try:
                await _maybe_await(phase.run_unit(job, self.cfg, unit))
                return
            except UnitFailed as exc:
                if attempt < len(RETRY_DELAYS):
                    await self._sleep(RETRY_DELAYS[attempt])
                    attempt += 1
                    continue
                job.failed_units.append(
                    {"phase": phase.name, "unit": unit.id, "error": str(exc)}
                )
                return

    async def advance_job(self, job: Job) -> None:
        """Advance ``job`` by one phase (or park it), persisting after every unit."""
        phase = self.phase_for(job.state)
        if phase is None:
            return  # no phase registered for this state (e.g. ingested pre-S5): idle

        if phase.is_gpu:
            self._wake(self.cfg)
            if not await self._gpu_gate(self.cfg):
                job.transition(JobState.WAITING_GPU)
                job.save(self.cfg)
                return
            # §7.4 mirror: a text/LLM GPU phase needs the card clear of SDXL, so release the image
            # GPU first. Render phases (``gpu_kind == "image"``) must NOT — they need it loaded.
            if getattr(phase, "gpu_kind", "text") == "text":
                await self._free_image_gpu(self.cfg)

        try:
            for unit in phase.units(job, self.cfg):
                if phase.unit_done(job, self.cfg, unit):
                    continue
                try:
                    await self._run_with_ladder(job, phase, unit)
                except GpuUnavailable:
                    job.transition(JobState.WAITING_GPU)
                    job.save(self.cfg)
                    return
                job.save(self.cfg)  # persist after every unit — resumability invariant
        except Exception:  # bug-class → fail the whole job (§7.3)
            job.transition(JobState.FAILED)
            job.save(self.cfg)
            return

        job.transition(phase.to_state)
        job.save(self.cfg)

    async def tick(self) -> None:
        """Advance the oldest runnable job by one phase (one job per tick)."""
        for job in jobmod.list_jobs(self.cfg):
            if not job.started or job.state in (
                JobState.PAUSED,
                JobState.FAILED,
                JobState.PUBLISHED,
                JobState.SET_DONE,
            ):
                continue
            if job.state == JobState.WAITING_GPU:
                # §7.4: retried each tick — resume to the GPU phase and re-gate.
                job.transition(job.prev_state or JobState.INGESTED)
                job.save(self.cfg)
            elif self.phase_for(job.state) is None:
                # A resting state with no worker phase (e.g. prompts_draft awaits the human
                # review gate). Normally there is nothing to run, so skip it rather than spend
                # the single per-tick slot on a no-op — otherwise one job parked at review would
                # starve every newer runnable job behind it.
                #
                # AUTO_APPROVE (ADR-0015): on a single-user LAN box the owner's "make this book"
                # click IS the approval, so apply the identical review-gate logic automatically
                # and let the now-``approved`` job advance to render this same tick. Not a bypass
                # — ``approve_job`` runs the same missing-prompt guard; a plate without a prompt
                # raises and the job stays parked for a human. Default off preserves invariant #4.
                if not (self.cfg.auto_approve
                        and job.state in (JobState.PROMPTS_DRAFT, JobState.IN_REVIEW)):
                    continue
                try:
                    approve_job(self.cfg, job)
                except (ApprovalBlocked, ValueError):
                    continue  # cannot auto-approve → leave parked for the human gate
            await self.advance_job(job)
            return  # single worker: one job advances per tick

    async def run_forever(self) -> None:
        """The worker loop. Runs until cancelled or :meth:`stop` is called."""
        try:
            while not self._stop:
                await self.tick()
                await self._sleep(self.cfg.runner_tick_s)
        except asyncio.CancelledError:  # pragma: no cover - shutdown path
            pass

    def stop(self) -> None:
        self._stop = True
