# ADR 0032: cast-review gate (approve character descriptions before the scene prompts derive)

- **Status:** Accepted
- **Date:** 2026-08-13
- **Relates to:** [ADR-0025](0025-portrait-review-gate.md) (the portrait gate, whose pattern this
  follows), [ADR-0015](0015-auto-approve.md) (auto-approve), [ADR-0002](0002-bundle-immutability.md)
  (immutability), DESIGN §7.3 (state machine), §11.1 (review gate).

## Context

Until now a bake generated everything before the first human stop: cast descriptions (P2) →
ledger (P3) → selection (P4) → **scene prompts (P5)** all ran, and the single review gate
(`prompts_draft`) presented the drafted scene prompts *and* the cast side-by-side. But the scene
prompts were already derived from the **un-reviewed** cast. When the owner then edited a character
at that gate, the scene prompts kept the stale character text and had to be re-edited plate by
plate. The owner wanted to **review the characters first**, and have the scene descriptions
generated from the approved cast.

A nuance surfaced while scoping: scene/page-plate prompts do not interpolate a character's full
`visual_description`. P5's `present_cast` passes only `name` + `one_line` to the `illustration-prompt`
LLM transform; the full description is baked only into the *portrait* prompt, and scene-render
character consistency comes from portrait-image conditioning (ADR-0023), not text. So the fix is
primarily about **ordering** — derive scene prompts only after the cast is approved — plus feeding
the approved appearance into the scene options so it can influence them.

## Decision

Add a **cast-review gate between P2 (cast generation) and P3 (ledger)**, always on, behaving exactly
like the `prompts_draft` gate.

**New states** (job.py `_CHAIN`, between `cast_running`'s product and the ledger):
`cast_done` becomes a **resting** review state (it loses its outgoing worker phase) and a new
`cast_approved` follows it. `LedgerEnter.from_state` moves from `cast_done` to `cast_approved`, so
P3 and everything downstream that reads the cast run only after approval. Neither is a GPU state; the
transition edges derive automatically.

**Gate decision** (runner.py, the same resting-state branch AUTO_APPROVE uses): at `cast_done` the
job **rests** for a human unless `auto_approve` is set, in which case `approve_cast` runs the same
guard automatically. Unlike the portrait gate (ADR-0025) this is not keyed on a per-book flag — it
is always in the chain — so on an attended box both text gates stop, and under AUTO_APPROVE both
clear themselves.

**Approval** (`approve.py approve_cast`, mirroring `approve_job`): a guard, not a bypass. It refuses
(`CastApprovalBlocked`, 422 with the offending `slugs`) if any `major` character still lacks a
`one_line` or `visual_description`, then transitions `cast_done → cast_approved`. Reused by both the
endpoint and the AUTO_APPROVE runner path.

**Reused review machinery** (review_api.py):
- `GET …/review` is tolerant at the cast gate — `selection.json`/`prompts/` don't exist yet, so it
  returns a cast-only payload (same keys, empty plate side).
- `edit_cast` is allowed at `cast_done` (its `rederive_portrait_prompt` is a no-op pre-P5).
- New `POST …/approve-cast` → `approve_cast`.

**Scene prompts read the approved appearance** (p5_prompts.py): `present_cast` now also emits a
condensed `appearance` (`subject_attributes(condense(visual_description))`, the same reduction the
portrait prompt uses) so the scene LLM sees the reviewed description, not just `one_line`. How
strongly it is used is owned by the external `illustration-prompt` template in text-transform-service
— this change only makes the data available.

**UI** (admin-ui): a `CastReview` screen at `#/book/{id}/cast` reusing the review payload + the
existing `CastPanel`/`editCast`, with an "approve cast" bar (422 refusal names the blank majors); a
state-gated "Review cast" button and the two new states spliced into the progress chain.

## Why this keeps the invariants

- **Immutability / byte-stability:** the gate touches only `cast.json` (already
  additive/human-editable) and adds a state transition. It never writes `pages/*.json` text,
  `structure.json`, or the paginator, and never mutates published bytes — the publish integrity
  guard is untouched. Toggle-independent: with `auto_approve` on, output is byte-identical to before
  (the offline P0→P8 golden bundle tests pass unchanged).
- **Review gate / causality:** the stop is a new gate, never a bypass — `approve_cast` runs the same
  kind of missing-artifact guard `approve_job` does. The cast is global identity (already shown at
  the later gate), so no new spoiler surface.

## Scope / limits

- The gate is unconditional (not a per-book flag). Existing in-flight bakes already past `cast_done`
  are unaffected; earlier ones gain the stop.
- Making scene prompts *strongly* honor `visual_description` depends on the text-transform-service
  `illustration-prompt` template (a separate repo) — out of scope here; this ADR only routes the
  data to it.
