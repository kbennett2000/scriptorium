# Handoff

## Current state
- **S6 complete** (PR open, awaiting human merge). P3 — the strictly-sequential scene-ledger
  pass. `bake/phases/p3_ledger.py` (`ledger_enter` + `p3_ledger`) registered after P2 on the
  already-legal `cast_done → ledger_running → ledger_done` edges — **no state-machine change**.
  Threads `scene-update` per page (`prior_ledger` = last *successful* stored ledger; `cast_names`
  from cast.json, `era` from bake_config), writes `ledgers/{id}.json`, then a **trailing `merge`
  pseudo-unit** folds each page's ledger onto `pages/*.json` (schema-validated) applying the
  §7.3 gap rule at phase end (a failed page inherits its predecessor + `carry_notes` gap note).
  Hand-written `scene-update` fixtures; capture tool extended to thread them on-LAN.
- **S5 complete** (merged): the cast pipeline's first real GPU phases:
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
- Server: `uv run pytest` → **142 passed, 3 deselected** (network + two gpu-live);
  `uv run ruff check .` (server + `tools/`) clean.

## Next up
- **S7** — P4 selection engine (pure `select()`, §8), **CPU-only**, `ledger_done → selected`.
  Input `PageScore = {seq, page_id, chapter, scene_changed, visual_salience}` — **numbers and
  booleans only, enforced structurally** (the spoiler invariant). Read the scores from the
  merged `pages/*.json` `ledger` (the gap-filled view), not raw `ledgers/*.json`. No GPU, so no
  enter-running phase needed; register on `ledger_done → selected`. Preset table as data (§8).
- **R1** — reader shell/shelf/checkout, unblocked since S3 (build against
  `server/tests/fixtures/bundle/`). **S12** (sync API) unblocked from S1.

## Open questions / blocked
- **Run the live checkpoint when convenient:** on the LAN with TTS T5 up, run
  `TTS_URL=… uv run python ../tools/capture_tts_fixtures.py` to replace the hand-written TTS
  fixtures (cast **and** scene-update) with real captures, and
  `uv run pytest -m gpu test_cast_live.py test_ledger_live.py -s` to paste real cast + ledger
  summaries into `CYCLE-LOG.md`. Not blocking development (fixtures suffice).
- See `NOTES-FOR-NEXT-CYCLES.md` "From S6": the trailing-pseudo-unit phase-end-finalize pattern;
  P3 threading (generation uses last-successful ledger, gap inheritance is merge-only); page
  ledgers now live on `pages/*.json` (P4 reads scores from there). "From S5": `cast_running`
  added; the GPU-phase enter pattern; `TtsClient` is the shared GPU-call surface (`unload_models`
  unused until P7); reducer intermediates live in `cast/groups.json`; the major-rule interpretation.
- "From S4/S3" still true: the job record is schema-free runtime state; `job.id == book_id`;
  P0 archival is user-source-only (wire gutenberg archival at M1); `system-overview.md`
  remains absent — treat DESIGN §1/§15 as canonical; paginator inheritances (verse ==
  any-`\n`; separator-ledger round-trip; page-id cap ≤9999).
