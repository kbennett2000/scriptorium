# Handoff

## Current state
- **S2 complete** (PR open, awaiting human merge). Ingestion adapters per DESIGN §5:
  Gutenberg (search/fetch/strip/heuristics), markdown (front-matter), textfile, the
  `RawBook`/registry in `ingest/base.py`, book-id derivation, raw-source archival, a dev
  CLI, and offline fixtures/tests.
- **S1 complete** (merged): monorepo skeleton + eleven JSON Schemas + generated TS types
  + ADRs + `/health` + `schemas.validate` + seeds.
- Server: `uv run pytest` → 48 passed, 1 deselected (network); `-m network` → 1 passed;
  `uv run ruff check .` clean.

## Next up
- **S3** — Paginator + golden tests + `make_fixture_bundle.py` (DESIGN §6). Consumes
  `RawBook` from S2; must align its NFC+`\n` normalization with
  `ingest.base.normalize_source_text`. Round-trip byte-equality is the load-bearing test.
- Also unblocked from S1 only: **S4** (job runner — will surface `RawBook.warnings` on
  jobs) and **S12** (sync API).

## Open questions / blocked
- None blocking. See `NOTES-FOR-NEXT-CYCLES.md`: `system-overview.md` still missing (the
  S2 pre-dispatch copy-in did not happen — non-blocking); ingestion decisions S3+ inherit
  (paragraphs keep internal `\n`; textfile does not strip PG boilerplate; internal `era`
  field; minimal front-matter parser); pytest now defaults to `-m 'not gpu and not network'`.
