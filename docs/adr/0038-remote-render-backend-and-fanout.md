# ADR 0038: a selectable render backend, and bounded parallel fan-out of plates

- **Status:** Accepted
- **Date:** 2026-08-18
- **Relates to:** ADR-0009 (GPU handoff / TTS unload before render), ADR-0011 (imagegen API),
  ADR-0023 / ADR-0026 / ADR-0028 (IP-Adapter references and per-plate conditioning),
  DESIGN §7.3, §7.4, §10.

## Context

Rendering is the second-largest bucket in a bake and the only one that is embarrassingly
parallel. Measured end to end on *The Legend of Sleepy Hollow* (`pg-41`, 9 plates + 6
portraits + cover = 16 renders) the home box spends **388.63 s**, of which **123.34 s** is
image rendering at a warm median of **7.595 s** per 832×1216 plate. Four independent bakes
put that per-plate constant between 7.44 s and 7.615 s, so it is stable.

It is also strictly serial, and deliberately so. `bake/runner.py` runs one asyncio worker
over one job at a time, and its docstring is explicit that the single worker *structurally*
enforces the §7.4 GPU-exclusivity rule: two GPU phases can never interleave because there is
only ever one of them. On a single-GPU box that reasoning is exactly right. The LLM and SDXL
cannot both be resident, which is why the render phases lead with an `__unload__` unit.

That reasoning is about **the** GPU. It stops applying the moment a plate renders somewhere
else. A pool of remote workers has no local card to be exclusive about, and 16 plates that
each take a few seconds on their own worker are 16 plates that need not wait for each other.

Measured against a Runpod serverless worker running the same ComfyUI graph, the same weights
and the same 25 sampler steps, a warm plate takes **4.406 s** on a pinned RTX 4090 — 42%
faster than home per plate, before any parallelism at all.

Two smaller things pushed in the same direction:

- **The imagegen base URL was the only render setting that was configurable.** Which backend,
  which card, and how many plates at once were not expressible.
- **Per-plate render timing was inferred, not recorded.** The external timing tool attributes
  ComfyUI log lines to plates by "the last render finishing at or before this plate's
  `render.at`". That is only sound while renders are serial. Under a fan-out it mis-attributes
  silently — the counts still add up, so no integrity check fires.

## Decision

**The render backend is configuration, and plate units may declare themselves parallel.**

- **A backend switch, defaulting to what exists.** `RENDER_BACKEND` selects `local` (the
  imagegen-service at `IMAGEGEN_URL`, the default) or `runpod` (a serverless endpoint named by
  `RUNPOD_ENDPOINT_ID`). `RENDER_CARD` names the GPU the operator expects. A new
  `RunpodImagegenClient` implements the existing `ImagegenClient` protocol, so `render_to_spec`
  and both render phases are untouched — only the injected object differs.

- **`IMAGEGEN_URL` keeps its existing role.** It is still what `free_imagegen_gpu` uses to
  release ComfyUI's VRAM before a text/LLM phase. That must keep happening even when plates
  render remotely, or the text steps run under different conditions than the baseline they are
  compared against. The render backend is a separate switch, not a replacement for the URL.

- **Only the bake's render phases switch.** The remote worker implements `txt2img` and nothing
  else — no img2img, no `/animate`, no checkpoint or style catalog. The post-publish picture
  editor, the admin model picker, the review-gate regeneration and per-user style-set
  re-illustration keep constructing `RealImagegenClient` directly. Routing them through a
  backend that raises on half their surface would be a wider change with its own reasons.

- **Parallelism is opt-in per unit, not per phase.** `Unit` gains `parallel: bool = False`.
  The render phases mark their plate units parallel and leave `__unload__` sequential, so the
  §7.4 handoff still completes alone and first. The runner groups consecutive parallel units
  into batches of `cfg.effective_render_concurrency` and gathers them, calling the **existing**
  `_run_with_ladder` per unit — so the 10/60/300 s retry ladder stays per plate, a single
  plate's `UnitFailed` never re-renders its neighbours, and `GpuUnavailable` still parks the
  job on `waiting_gpu`.

- **Concurrency is clamped to 1 on the local backend**, whatever `RENDER_CONCURRENCY` says.
  imagegen-service is concurrency-safe at the HTTP layer, but it proxies one ComfyUI on one
  card, which serialises the work anyway. Fanning out there buys no speed, risks the service's
  300 s generate budget on whichever plates end up last in the queue, and breaks render-timing
  attribution. **At concurrency 1 the batching is a no-op and the code path is what it was.**

- **A batch that raises does not cancel its siblings.** `gather(..., return_exceptions=True)`
  lets in-flight renders finish before the exception is re-raised. A cancelled remote render
  has already been paid for and leaves no artifact for `unit_done` to skip on resume.

- **The backend's own report becomes provenance.** A client may expose `last_echo`; P7 folds it
  into `render.params_echo` beside the seed and size. The Runpod worker reports its own
  `render_s` / `model_load_s` / `total_s`, the card it ran on, and the sampler settings the
  graph was built with. A number the renderer reports about itself needs no attribution, which
  is what makes per-plate timing survive a fan-out. `params_echo` is schema-declared opaque
  ("shape owned by the imagegen service"), so **no schema change and no type regeneration**.

- **`RENDER_CARD` is an assertion, not a request.** The card is pinned where the endpoint is
  declared. A serverless pool can substitute a different card of the same VRAM tier without
  saying so — measured: a request for an A5000 or 3090 ran every job on an RTX PRO 6000
  Blackwell MIG slice, while a single pinned 4090 was honoured. A mismatch logs a warning and
  returns the render, because the pixels are real; it is the comparability of the timing that
  is not.

## Consequences

- A bake can render on hardware the bakery does not own, with no change to phase code, and the
  home path is byte- and behaviour-identical by default.
- Pause now lands per batch rather than per unit during a fan-out. At concurrency 1 — every
  local deployment — a batch is a unit, so nothing changes.
- **Determinism is now conditional on hardware.** SDXL at a fixed seed is deterministic on the
  same silicon and kernels; it is not across architectures. Re-baking a book on a different
  card produces a different, equally valid book. Anything that depends on a plate re-rendering
  identically holds only while the card is held constant.
- A remote render adds network transfer to the per-plate cost: the PNG returns base64 in the
  response body (~1.4–1.7 MB per plate), and an IP-Adapter reference portrait travels base64 in
  the request. That is deliberate — it keeps character artwork out of the container image and
  out of the registry.

## Alternatives considered

- **Fan out inside `run_unit`**, emitting one batch unit per group. Smaller diff, and it never
  touches the runner. Rejected: `_run_with_ladder` is per unit, so the retry ladder would
  re-render plates that had already succeeded; one plate's 422 would poison its batch;
  `failed_units` would name a batch rather than a plate; and Pause could not land until the
  batch drained.
- **A global concurrency setting with no per-unit flag.** Rejected: the render phases mix a
  unit that must be exclusive with units that need not be, and only the phase knows which is
  which. Making the runner infer it from unit ids would be guessing.
- **Replacing `IMAGEGEN_URL` with the backend switch.** Rejected: it is still needed for the
  §7.4 VRAM release, which is not a rendering concern.
