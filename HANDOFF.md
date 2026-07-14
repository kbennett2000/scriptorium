# Handoff

## Current state
- **S5 complete** (PR open, awaiting human merge). The cast pipeline's first real GPU phases:
  `bake/tts_client.py` (async TTS client + §8 error-taxonomy mapping), `bake/reduce_cast.py`
  (the §7.2 reducer as a pure function), `bake/phases/p1_mentions.py` + `bake/phases/p2_cast.py`
  (four phases — `mentions_enter`, `p1_mentions`, `p2_reduce`, `p2_canonicalize`) registered
  into the runner pipeline in `app.py`. Added a `cast_running` GPU state (approved deviation)
  so P2's canonicalize parks on `waiting_gpu` like every other GPU phase. Hand-written TTS
  fixtures under `server/tests/fixtures/tts/` + `tools/capture_tts_fixtures.py` to re-capture
  them on-LAN. New `PipelineBug` exception (400/404/413-class → job `failed`).
- **S4 complete** (merged): bake orchestration mechanics — `bake/job.py` (Job + §7.3 state
  machine + atomic persistence), `bake/runner.py` (single asyncio worker, per-unit
  persistence, 3× retry ladder, `waiting_gpu`+WoL), `bake/phases/base.py` (Phase protocol +
  exceptions), `bake/api.py` (admin endpoints; P0 inline). Kill-test proves ≤1 unit lost.
- **S3 / S2 / S1 complete** (merged): paginator + fixture bundle; ingestion adapters;
  monorepo skeleton + schemas + generated TS types + `/health`.
- Server: `uv run pytest` → **137 passed, 2 deselected** (network + gpu-live);
  `uv run ruff check .` (server + `tools/`) clean.

## Next up
- **S6** — P3 (scene ledger + salience scoring, transform `scene-update`), **strictly
  sequential** per page with contiguity resume (§7.3). Needs the same "enter the running
  state" pattern (CPU step onto `ledger_running`, then the GPU phase) and TTS fixtures — use
  `tools/capture_tts_fixtures.py` as the template. Register after `p2_canonicalize`
  (`cast_done → ledger_running → ledger_done`).
- **S7** — P4 selection engine (pure `select()`, §8), CPU-only, `ledger_done → selected`.
- **R1** — reader shell/shelf/checkout, unblocked since S3 (build against
  `server/tests/fixtures/bundle/`). **S12** (sync API) unblocked from S1.

## Open questions / blocked
- **Run the live checkpoint when convenient:** on the LAN with TTS T5 up, run
  `TTS_URL=… uv run python ../tools/capture_tts_fixtures.py` to replace the hand-written TTS
  fixtures with real captures, and `uv run pytest -m gpu test_cast_live.py -s` to paste a real
  cast summary into `CYCLE-LOG.md`. Not blocking S6 (fixtures unblock development).
- See `NOTES-FOR-NEXT-CYCLES.md` "From S5": `cast_running` added; the GPU-phase enter pattern;
  `TtsClient` is the shared GPU-call surface (`unload_models` unused until P7); reducer
  intermediates (`is_person`/`descriptors`) live in `cast/groups.json`, not `cast.json`; the
  major-rule interpretation.
- "From S4/S3" still true: the job record is schema-free runtime state; `job.id == book_id`;
  P0 archival is user-source-only (wire gutenberg archival at M1); `system-overview.md`
  remains absent — treat DESIGN §1/§15 as canonical; paginator inheritances (verse ==
  any-`\n`; separator-ledger round-trip; page-id cap ≤9999).
