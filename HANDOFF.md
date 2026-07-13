# Handoff

## Current state
- **S4 complete** (PR open, awaiting human merge). Bake orchestration mechanics, proven with
  fake phases before any real phase exists: `bake/job.py` (Job model + §7.3 state machine as a
  transition table + atomic JSON persistence), `bake/runner.py` (single asyncio worker,
  directory-scan queue, per-unit persistence, 3× retry ladder, `waiting_gpu`+WoL),
  `bake/phases/base.py` (Phase protocol + `GpuUnavailable`/`UnitFailed`), `bake/api.py`
  (`POST /api/admin/books` runs P0 inline; list/detail; `PUT chapters` 409 guard;
  `start|pause|resume`). One task started in the app lifespan → single-worker/GPU exclusivity
  is structural. Kill-test proves ≤1 in-flight unit lost on restart.
- **S3 complete** (merged): paginator per DESIGN §6 (`paginate/engine.py`), byte-stable +
  deterministic, separator-ledger round-trip; `structure.json`; `schemas.validate` on every
  output; `tools/make_fixture_bundle.py` + the committed fixture bundle
  (`server/tests/fixtures/bundle/`, R1's dev diet).
- **S2 complete** (merged): ingestion adapters (Gutenberg, markdown, textfile), `RawBook`,
  book-id derivation, CLI, fixtures.
- **S1 complete** (merged): monorepo skeleton + eleven JSON Schemas + generated TS types
  + ADRs + `/health` + `schemas.validate` + seeds.
- Server: `uv run pytest` → 107 passed, 1 deselected (network); `uv run ruff check .`
  (server + tool) clean.

## Next up
- **S5** — P1+P2 (mentions, reducer, canonicalize). Register the first real phases into the
  runner's pipeline (replace `Runner(cfg, pipeline=[])` in `app.py`'s lifespan). Needs TTS
  fixtures. See `NOTES-FOR-NEXT-CYCLES.md` "From S4" for the phase-plug-in contract
  (`from_state`/`to_state` must be a legal edge; `units`/`unit_done`/`run_unit`; failure
  taxonomy; `is_gpu` gate).
- **R1** — Reader shell/shelf/checkout/reading surface, unblocked since S3: build against
  `server/tests/fixtures/bundle/`.
- Also unblocked from S1 only: **S12** (sync API).

## Open questions / blocked
- None blocking. See `NOTES-FOR-NEXT-CYCLES.md` "From S4": the job record is deliberately
  schema-free runtime state; `job.id == book_id` (one job per book); real pipeline is P0-only
  until S5 registers P1; P0 archival is user-source-only (wire gutenberg archival at M1);
  render (P7) needs an imagegen-health gate + a TTS `models/unload` precondition at S10.
- "From S3" (still true): `system-overview.md` remains absent — treat DESIGN §1/§15 as
  canonical; paginator inheritances (verse == any-`\n`; separator-ledger round-trip; 4-digit
  page-id cap ≤9999); fixture-bundle image determinism depends on the installed Pillow version.
