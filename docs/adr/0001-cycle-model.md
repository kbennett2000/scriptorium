# ADR 0001: Cycle model

- Execution runs as headless `claude -p`, one cycle per run.
- Fresh session each cycle; state lives in HANDOFF.md, CLAUDE.md, and ADRs — not resumed context.
- Work happens on a branch, never main. Human merges.
- When unsure or blocked: commit what exists, write the question into the issue, stop.
