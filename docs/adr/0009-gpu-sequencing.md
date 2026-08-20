# ADR 0009: GPU sequencing — one worker, unload before render, wake on wait

- **Status:** Superseded by [ADR-0039](0039-server-side-gpu-tenancy-lock.md)
- **Date:** 2026-07-13

> **Superseded (2026-08-20).** GPU exclusivity moved server-side: the text-transform-service and
> imagegen-service now share an advisory `flock` GPU-tenancy lock, and each frees its own VRAM
> before releasing it. Scriptorium no longer performs the client-side handoffs described below —
> the pre-render TTS `unload` and the direct-ComfyUI `/free` are both removed. The single-worker
> queue and the Wake-on-LAN / health gate remain. See ADR-0039.

## Context

Two GPU services share one 5070: the text-transform-service (LLM) and the imagegen
service (SDXL). They cannot both hold VRAM at once, the GPU box may be asleep, and
any process may die mid-bake. See DESIGN §7.3, §7.4, §11.2, and §1 principles 5–6.

## Decision

- A **single** asyncio job worker runs the whole bakery, so LLM phases and render
  phases can never interleave — GPU exclusivity comes for free from serialization.
- Before entering the render phase (P7), the runner calls the transform service's
  `POST /v1/models/unload` and requires success; otherwise the job goes
  `waiting_gpu`.
- At job start and on every `waiting_gpu` retry, the runner sends Wake-on-LAN to
  the GPU box (guarded by `GPU_WOL_ENABLED`/`GPU_MAC`) and polls the relevant
  service's health before proceeding.

## Consequences

- No Celery/Redis: jobs are JSON files, the queue is a directory scan, and there
  is exactly one worker, which also enforces GPU exclusivity.
- GPU-unavailable is a normal, resumable state (`waiting_gpu`), retried each tick
  (`RUNNER_TICK_S`, default 120s), not a failure.
- The runner and WoL helper are built and tested with a fake GPU in cycle S4;
  real sequencing is observed at S10.
