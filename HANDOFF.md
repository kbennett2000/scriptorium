# Handoff

## Current state
- **S3 complete** (PR open, awaiting human merge). Paginator per DESIGN §6:
  `paginate/engine.py` (`paginate(RawBook, params) -> PaginatedBook`), byte-stable and
  deterministic, with a separator ledger so chapters round-trip byte-exactly across
  sentence/line splits; `structure.json` emission; `schemas.validate` on every output;
  `tools/make_fixture_bundle.py` + the committed fixture bundle
  (`server/tests/fixtures/bundle/`, R1's dev diet).
- **S2 complete** (merged): ingestion adapters (Gutenberg, markdown, textfile), `RawBook`,
  book-id derivation, CLI, fixtures.
- **S1 complete** (merged): monorepo skeleton + eleven JSON Schemas + generated TS types
  + ADRs + `/health` + `schemas.validate` + seeds.
- Server: `uv run pytest` → 74 passed, 1 deselected (network); `-m network` → 1 passed;
  `uv run ruff check .` (server + tool) clean.

## Next up
- **S4** — Job runner + state machine (fake phases). Wire P0 = `ingest.load` → `paginate`
  → archive source (`ingest.base.archive_source`) → persist `pages/*.json` + `structure.json`;
  surface `RawBook.warnings` on the job. Consumes S3's paginator.
- **R1** — Reader shell/shelf/checkout/reading surface, now unblocked: build against
  `server/tests/fixtures/bundle/`.
- Also unblocked from S1 only: **S12** (sync API).

## Open questions / blocked
- None blocking. See `NOTES-FOR-NEXT-CYCLES.md` "From S3": `system-overview.md` is still
  absent after three cycles (recommend dropping it as required reading — DESIGN §1/§15 is
  canonical); paginator inherits (verse == any-`\n`; separator-ledger round-trip; 4-digit
  page-id cap ≤9999); fixture-bundle determinism depends on the installed Pillow version.
