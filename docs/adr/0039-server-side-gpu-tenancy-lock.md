# ADR 0039: Server-side GPU-tenancy lock — drop client-side sequencing

- **Status:** Accepted
- **Date:** 2026-08-20
- **Supersedes:** [ADR-0009](0009-gpu-sequencing.md)

## Context

The bake pipeline is a **client** of two LAN GPU microservices that share one card: the
text-transform-service (TTS, `:8712`) and the imagegen-service (`:8189`, a ComfyUI `:8188` proxy).
Under ADR-0009 Scriptorium owned GPU exclusivity itself with two client-side handoffs:

- **Unload the LLM before every render** — the render phase's leading unit called TTS
  `POST /v1/models/unload` and required success.
- **Free ComfyUI's VRAM before every text phase** — the runner discovered ComfyUI's URL from
  imagegen-service `/health` (`comfyuiUrl`) and POSTed ComfyUI's `/free` directly.

Both services have since gained a shared **advisory `flock` GPU-tenancy lock**. Whoever holds the
lock loads its model, drains its work, **frees its own VRAM, then releases** the lock. Coordination
that Scriptorium used to perform is now redundant — and the direct-ComfyUI `/free` is actively
unsafe: it reaches *around* the lock into another tenant's VRAM, possibly mid-render, which is
exactly the collision the lock exists to prevent.

A second consequence: a call can now **block on the lock** for minutes (queued behind a ~20-minute
Wan video render) instead of instantly `503`-ing. ADR-0011 noted the imagegen `/health` has "no busy
signal"; that is now moot for the *work* calls — `/generate` and `/animate` simply wait on the lock
rather than surfacing busy-ness. Our old client read timeouts (transform 120s, generate 300s) were
short enough that a lock-blocked call timed out and re-queued `waiting_gpu` every tick — graceful but
wasteful, and it logged a false "service unreachable".

This is a **client-side-only** change. Scriptorium does not implement the lock, never touches the
lockfile, and still reaches the GPU only through `:8712` / `:8189` (never ComfyUI directly).

## Decision

- **Remove the direct-ComfyUI `/free` bypass.** `free_imagegen_gpu()` and its runner wiring are
  deleted. The runner keeps only the Wake-on-LAN pulse and the `/health` reachability gate before a
  GPU phase.
- **Remove the pre-render TTS unload.** The render phases' leading `__unload__` unit (in
  `p7_render.py` and `artsets/phase.py`) no longer calls `unload_models()`. It **keeps** the imagegen
  `health()` gate — `/health` is never lock-covered, so it still distinguishes a down service (→
  `GpuUnavailable` → `waiting_gpu`) from a merely-busy one a render call will block behind.
  `TtsClient.unload_models()` stays as a manual tool, just off the automatic path.
- **Lengthen and make tunable the block-tolerant timeouts.** The transform, `/generate`, and
  `/animate` read timeouts move to `Config` (env-overridable, default `1200s`), high enough to clear
  a max render/video queued ahead of them instead of timing out. The short `/health` / unload /
  probe timeouts stay as-is.

## Consequences

- A bake queued behind a long render now **blocks on the lock and completes**, rather than churning
  `waiting_gpu` each tick. Genuine service-down still raises `GpuUnavailable → waiting_gpu → retry`;
  only the timeout length before that verdict changes.
- The lock is **fail-open**: if the lockfile is missing the services run unlocked and contention
  returns to pre-lock levels. That is the accepted degraded mode — Scriptorium does **not** re-add a
  client-side `/free` to paper over it (doing so would reintroduce the cross-tenant hazard).
- The single-worker queue (ADR-0009) is unchanged and still structurally serialises the pipeline;
  the GPU-sharing invariant it used to enforce for LLM-vs-SDXL is now owned server-side.
- No new secrets or endpoints; the timeout env vars (`TTS_TRANSFORM_TIMEOUT_S`,
  `IMAGEGEN_GENERATE_TIMEOUT_S`, `IMAGEGEN_ANIMATE_TIMEOUT_S`) follow the existing `*_URL` pattern.
