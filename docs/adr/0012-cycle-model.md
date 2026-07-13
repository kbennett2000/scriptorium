# ADR 0012: Cycle model

- **Status:** Accepted
- **Date:** 2026-07-13

> Renumbered from ADR-0001 in cycle S1: DESIGN §15 reserves ADR-0001…0010 for the
> system invariants (0001 = monorepo/schemas). This decision predates that
> numbering and is preserved here. (0011 is reserved for the imagegen-service API
> ADR, written in cycle S10.)

## Context

Work on this repo is executed by a headless `claude -p` run, one cycle per
dispatch, with no persistent session and no human watching. State cannot live in
remembered conversation.

## Decision

- Execution runs as headless `claude -p`, one cycle per run.
- Each cycle starts fresh; state lives in `HANDOFF.md`, `CLAUDE.md`, and the ADRs
  — not resumed context.
- Work happens on a branch, never `master`/`main`; a human merges.
- When unsure or blocked: commit what exists, write the question into the issue,
  and stop.

## Consequences

- Every cycle reads `HANDOFF.md`, `CLAUDE.md`, and the ADRs at start and updates
  `HANDOFF.md` at end.
- No cycle ends by pausing for input; it either completes (PR opened) or records a
  blocker on the issue and exits (see `CLAUDE.md`).
