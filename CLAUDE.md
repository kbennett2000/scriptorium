# CLAUDE.md

<!-- Everything above the PROJECT CONTEXT marker is inherited from project-template.
     Do not edit per-project. Project-specific content is appended below the marker
     by the factory generator from the new-project issue. -->

## How work runs here

- Work is executed one cycle at a time by a headless `claude -p` run — no persistent session, and no human watching the run.
- Each cycle starts fresh. Current state lives in `HANDOFF.md`, the ADRs under `docs/adr/`, and this file — not in remembered conversation. Read them at the start of every cycle.
- End each cycle by updating `HANDOFF.md` so the next cycle can pick up cleanly.

## The cycle contract

**Never pause or wait for a human.** No one is watching the terminal. You must never end by printing a question and stopping — a question that isn't recorded on the issue is lost. Every cycle ends in exactly one of the two terminal states below, then exits.

**Do the work. Don't ask permission.** When files change, you ALWAYS — without asking, every time:
1. Work on a branch, never `master`/`main`.
2. Commit and push.
3. Open a PR for human review/merge.

Committing, pushing, and opening a PR are never optional and never require confirmation. A human reviews and merges the PR; you do not close the issue.

**Decide, don't stall.** If something is uncertain but you can proceed, make the reasonable choice and note it in the PR description. "Should I also do X?" is not a blocker — do the obvious thing or note it and move on. Non-blocking uncertainty never stops a cycle.

**Stopping early is rare and only for true blockers.** Stop only when you are missing information you genuinely cannot proceed without. Stopping means: record the blocker on the issue (the `needs-input` state below) and exit. This is recording, not asking — you never wait for a reply. A destructive or unwalkbackable action (force push, history rewrite, deleting branches/data) counts as a blocker: do not do it; record it and stop.

## End of cycle — always update the issue

You are given the instruction issue number for this cycle (e.g. #1). Before you exit, run exactly one case:

- **Completed** (files changed, PR opened):
  - `gh issue comment <N> --body "PR: <pr-url>"`
  - `gh issue edit <N> --add-label cycle-summary --remove-label instructions`
- **Blocked** (missing info you cannot proceed without):
  - `gh issue comment <N> --body "<the blocker, stated clearly>"`
  - `gh issue edit <N> --add-label needs-input --remove-label instructions`

Every cycle ends in one of these two states, then stops. Never close the issue.

## Conventions

- ADR-first: significant decisions get an ADR in `docs/adr/` before implementation.
- Keep changes small and reviewable.

<!-- ===== PROJECT CONTEXT (appended per repo — do not add content above this line) ===== -->

## Project context

     What this project is, stack, test command, project-specific conventions. -->
