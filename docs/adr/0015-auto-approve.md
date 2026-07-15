# ADR-0015 — Optional auto-approve of the review gate (`AUTO_APPROVE`)

Status: accepted (2026-07-14)

## Context

Invariant #4 (CLAUDE.md hard rules, system-overview §5) is **"no plate rendered before human
approval."** The pipeline enforces it structurally: a bake rests at `prompts_draft`, and only the
review gate's `approve` advances it to `approved`, where the render phase (P7) picks it up. The
gate exists to (a) avoid spending money/GPU time on renders nobody wanted, and (b) let a human
catch spoilers or bad prompts before dozens of plates are drawn.

The product owner runs the whole system on **one machine, as the only user**, with a **local GPU**
where rendering is free and fast. In that deployment the gate is a manual speed bump with no payoff:
the owner already expressed intent by clicking "make this book," there is no per-render cost, and
there is no second reviewer. They asked to remove the review step.

## Decision

Add an **opt-in** `AUTO_APPROVE` env flag (default **false**). When true, the single runner, on
finding a job resting at `prompts_draft` (or the transient `in_review`), calls the **same**
approval logic the human endpoint calls and lets the now-`approved` job advance to render on the
same tick.

To guarantee "same gate, not a bypass," the approval logic was extracted from `review_api.approve`
into `bake/approve.py::approve_job`, and both callers use it. Auto-approve therefore runs the
identical **missing-prompt guard**: if any renderable plate lacks a prompt artifact, `approve_job`
raises and the runner leaves the job parked for a human — it never renders a half-derived shot list.

## Why this does not weaken invariant #4

- **The default is unchanged.** With `AUTO_APPROVE` unset, behaviour and every existing test are
  byte-identical: the gate still blocks render until a human approves. The invariant holds for the
  shipped default and the deployed i5 box.
- **The opt-in is explicit and logged in config**, exactly like `SCRIPTORIUM_DATA`/`TTS_URL` — an
  operator's deliberate choice for a specific box, not a code path that silently skips review.
- **It is the same gate.** Auto-approve reuses `approve_job`; the guard against rendering a plate
  with no prompt still fires. The "approval" is relocated from a screen click to the owner's
  upstream "make this book" click — appropriate for a single-user, zero-cost-render deployment.
- **No new render path.** Rendering still happens only in P7 off the `approved` state on the single
  worker (GPU sequencing, TTS-unload-before-render, `waiting_gpu` on `GpuUnavailable` all intact).

## Consequences

- On a box launched with `AUTO_APPROVE=1`, books flow `prompts_draft → approved → rendering`
  without human interaction; the review/edit endpoints remain available but are not required.
- Turning the gate back on is a one-line change: drop the env var (or set `AUTO_APPROVE=0`) and
  restart.
- The review-edit endpoints (edit prompt/cast/selection, reselect) are unaffected — they still
  guard on the pre-approval states; auto-approve simply advances past them when nobody intervenes.

## Alternatives considered

- **Delete the gate outright.** Rejected: it would break invariant #4 for every deployment and the
  tests that protect it, and make restoring review real rework. The flag gives the owner the same
  outcome while keeping the invariant true by default and fully reversible.
- **Auto-approve inside the P0 create endpoint.** Rejected: rendering must never be triggered from a
  request handler (GPU sequencing lives on the single runner). The flag keeps approval on the
  runner, where it belongs.
