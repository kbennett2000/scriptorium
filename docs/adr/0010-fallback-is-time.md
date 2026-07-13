# ADR 0010: Fallback is time — no paid providers

- **Status:** Accepted
- **Date:** 2026-07-13

## Context

Bake-time work depends on local GPU services that may be unreachable, asleep, or
briefly failing. The tempting "fix" is to fall back to a paid cloud API. That
would put API keys in this repo and make cost, not time, the failure currency.
See DESIGN §1 principle 5, §7.3.

## Decision

There are no paid providers and no API keys anywhere in this repo. When a GPU
service is unavailable the bake **pauses and later resumes** — fallback is time,
never money. The transform/imagegen error taxonomy (per the text-transform-service
DESIGN §8) is consumed as pause/retry signals: 503-class → `waiting_gpu` (retry);
422 → a failed unit (bounded retry, then recorded); 400/404/413 → a pipeline bug
that fails the phase loudly for human attention.

## Consequences

- The system is free to run indefinitely at zero marginal cost; a slow GPU or a
  sleeping box costs latency, not dollars.
- Error handling maps external failures onto exactly three internal outcomes
  (wait / unit-fail / bug), implemented in the transform client in cycle S5.
- No secret management is needed for generation.
