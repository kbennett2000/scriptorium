# Handoff

## Current state
- **S1 complete** (PR open, awaiting human merge). Monorepo skeleton + all eleven
  JSON Schemas + generated TS types + ADRs 0000/0001–0010/0012 + `/health` +
  `schemas.validate` + seeds + tests.
- Server: `uv run pytest` → 29 passed; `uv run ruff check .` clean.
- reader & admin-ui scaffolds: lint + typecheck + build green.
- TS type generation is deterministic (verified).

## Next up
- **S2** — Ingestion adapters (txt/gutenberg, markdown, upload) per DESIGN §5.
  Depends on S1 only. Also unblocked: **S4** (job runner) and **S12** (sync API),
  which need only S1 schemas.
- Schemas are frozen contracts now; later cycles consume `scriptorium.schemas`
  and `shared/types` rather than redefining formats.

## Open questions / blocked
- None blocking. See `NOTES-FOR-NEXT-CYCLES.md` for environment prerequisites
  (`just`, `wakeonlan`, GPU env vars) and the missing `system-overview.md`.
