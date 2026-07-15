# ADR 0011: imagegen-service API binding — evidence-first client for P7

- **Status:** Accepted
- **Date:** 2026-07-13

## Context

S10's render phase (P7) needs a real image-generation client. DESIGN §10 assumes a
service that can produce **832×1216** plates/cover and **1024×1024** portraits, accept a
**negative prompt**, and take a **seed** (for regen). Per BUILD-PLAN §0/S10 those are
assumptions to verify against the real service before building — so this ADR records the
actual `imagegen-service` HTTP API (read at `~/Desktop/projects/imagegen-service`,
commit `8660ab6`) and the client binding, and it captures a **hard gate** the evidence
surfaced. See DESIGN §10 (assembly/sizes), §7.4 / ADR-0009 (GPU sequencing).

`imagegen-service` is a **TypeScript / `node:http`** proxy in front of a local **ComfyUI**
instance (not FastAPI). It listens on **:8189**, binds `0.0.0.0`, is **file-config only**
(no env vars), and returns **raw PNG bytes** — callers persist them.

### Verified endpoint map

| Method | Path | Notes |
| --- | --- | --- |
| `POST` | `/generate` | Body `{prompt (req), negativePrompt?, style?, quality? (fast\|standard\|high, default standard), seed? (int)}`. Success → **`200 image/png` raw bytes**. `422` bad body, **`503` any ComfyUI failure**, `401` if auth on. Unknown body fields ignored. |
| `GET` | `/health` | Never auth-gated, always `200`. Body `{comfyuiReachable: bool, comfyuiUrl, lorasLoaded[]}`. GPU-down = `comfyuiReachable:false`; **no busy/queue signal**. |
| `GET` | `/styles` | LoRA-backed style presets. Not used by scriptorium (style rides in the prompt). |

- **Negative prompt:** supported — field `negativePrompt`, appended to the workflow's
  baseline negatives. ✅ (DESIGN §10 requirement met.)
- **Seed:** supported — field `seed` (int); omitted → random per call. ✅ (regen passes a
  fresh seed.)
- **No** model load/unload/warmup endpoint (ComfyUI lazy-loads on the first `/generate`);
  **no** sampler/cfg/steps/model params (only the `quality` tier).

### The hard gate — image size

The service produces a **fixed 1024×1024 square**. There is **no `width`/`height`/`size`
parameter**: dimensions are hardcoded in `src/workflows/{sdxl-txt2img,sdxl-refiner}.json`
node `"5"` (`EmptyLatentImage`), and the engine never mutates them. DESIGN §10's
**832×1216** plates/cover are therefore **impossible** against the service as-shipped —
exactly the "stop and report before building" condition BUILD-PLAN/S10 Task 0 calls out.

## Decision

- **Extend imagegen-service** (a small, backward-compatible PR to that repo, cycle S10a):
  `POST /generate` gains optional `width`/`height` (validated: positive ints, multiple of
  8, sane SDXL bounds) wired to the `EmptyLatentImage` node, **defaulting to 1024×1024** so
  existing callers are unaffected. This lets scriptorium request §10 sizes without changing
  the design. (Alternatives rejected: rendering square and deviating from §10; or cropping/
  padding 1024² in scriptorium — both degrade the illustrated-book output.)
- **`RealImagegenClient`** (`server/src/scriptorium/render/imagegen.py`) binds the API:
  - `txt2img(prompt, negative, width, height, seed)` → `POST /generate`
    `{prompt, negativePrompt, width, height, seed?}`, returns the PNG bytes.
  - `health()` → `GET /health`, returns the `comfyuiReachable` boolean.
  - **Error mapping** (mirrors `TtsClient`, feeds the runner taxonomy §7.3): `503` /
    connection / timeout → `GpuUnavailable` (→ `waiting_gpu`, retried); `422` → `UnitFailed`
    (→ ladder → `failed_units`); any other status → `PipelineBug` (halt loudly). An unset
    `IMAGEGEN_URL` makes `health()` False and `txt2img` raise `GpuUnavailable`.
- **GPU gate for render:** the service exposes no load/unload hook, so P7 keeps the
  ADR-0009 sequence itself — the render phase's leading unit calls TTS
  `POST /v1/models/unload` (require success) and then `client.health()`; either failure
  parks the job on `waiting_gpu`. `FakeImagegen` stays the offline test double.

## Consequences

- P7 can render to §10 sizes **once the imagegen-service size PR is merged and deployed**.
  Until then, only `FakeImagegen` honours width/height; an older real service silently
  returns 1024² (documented risk, surfaced by the gpu-marked live test's size assertion).
- The client is style-neutral (style is baked into the prompt by P5/P7), so `style`/LoRA
  selection and the `quality` tier are **not** used by scriptorium; if step/cfg control is
  ever needed it requires another imagegen-service change (no per-call knobs today).
  **Updated by ADR-0013:** the client now *optionally* forwards `style` (a LoRA preset name)
  so catalog styles can carry the real Chronicle look; prompt-only styles pass `null` and
  keep this style-neutral behaviour.
- `/health` cannot distinguish GPU-busy from GPU-down (only `comfyuiReachable`). A busy GPU
  surfaces as a slow `/generate` that eventually `503`s on the tier timeout → `GpuUnavailable`,
  which is the correct park-and-retry behaviour anyway.
- No API keys or secrets are introduced (the service's auth token, if any, is off by default
  and lives in its own config, never in this repo).
