# ADR 0024: a TTS 5xx is a retriable per-unit fault, not a whole-job bug

- **Status:** Accepted
- **Date:** 2026-08-11
- **Relates to:** DESIGN §7.3 (bug-class → fail job), §8 (TTS error taxonomy), [ADR-0020](0020-auto-start.md)
  (unattended auto-start). Companion fix upstream: text-transform-service **T17**.

## Context

An unattended 600-page bake (*The Brothers Karamazov*) failed at **page 301 of 600**. The text
service returned a one-off `500 Internal Server Error` on that page's `cast-mentions` call: the LLM
had emitted a lone UTF-16 surrogate (`\ud835`) that the service could not UTF-8 encode (fixed at the
source in TTS T17). The failure was **stochastic** — the same page succeeds on a re-run.

`TtsClient._map_error` mapped every non-2xx status except 503/422 — including **500** — to
`PipelineBug`, a bug-class exception that fails the *entire* job (§7.3). So a single transient hiccup
on one page discarded 300 pages of completed work and the whole overnight run, with no retry. That
directly defeats the product intent behind AUTO_START (ADR-0020): "kick off a bake, go to bed, wake up
to a finished book."

## Decision

Split the TTS error taxonomy by **who is at fault**:

- **5xx (server-side, transient)** → `UnitFailed`. Retried on the runner's 3× ladder (10/60/300s);
  exhausting it records the unit in `failed_units` and the bake **continues**. Joins the existing
  `422 → UnitFailed` (validation) path. A stochastic 500 almost always clears on the next attempt.
- **503 (busy / model unavailable)** → `GpuUnavailable` (unchanged) → `waiting_gpu`.
- **4xx (client-side: 400/401/404/413, …)** → `PipelineBug` (unchanged). A malformed request,
  unknown transform, oversized payload, or auth failure will not fix itself on retry — halt loudly.

One line in `_map_error`: `if status in _UNIT_FAILED_STATUS or status >= 500`.

## Consequences

- **Resilience:** no single page can kill an unattended multi-hundred-page bake; the worst case for a
  genuinely-persistent 5xx is one skipped unit (for `cast-mentions`, one page's mentions), not a dead
  job. This is the same degradation already accepted for 422.
- **Loudness preserved for real bugs:** 4xx still halts, so a genuine wiring/contract error surfaces
  immediately rather than being silently retried away.
- **Invariants untouched:** no change to GPU sequencing, the review gate, immutability, or
  determinism — only the exception a non-2xx status maps to. Covered by parametrized
  `test_tts_client` cases (500/502/504 → `UnitFailed`; 400/401/404/413 → `PipelineBug`).
