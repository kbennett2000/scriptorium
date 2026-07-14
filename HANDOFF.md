# Handoff

## Current state
- **S7 complete** (PR open, awaiting human merge). P4 — the deterministic selection engine.
  `selection/engine.py` (`select(scores, structure, params)`, §8 steps 1–5; `PageScore`/`Params`/
  `PlateChoice` frozen dataclasses + `PRESETS` table; the **spoiler invariant made structural** —
  `PageScore` is numbers/booleans/id only), `selection/reselect.py` (the §8 re-selection diff,
  standalone/unit-tested), and `bake/phases/p4_select.py` (the pipeline's **first rest→rest CPU
  phase**, `ledger_done → selected`, `is_gpu=False`, no enter step) registered after P3. **No
  state/schema/runner change** (edge + `SELECTED` + `"selection"` kind pre-existed). Reads scores
  only from `pages/*.json`. Documented interpretation: the fill window is intersected with
  `min_gap` so the global min_gap property holds. Plate counts on the committed synthetic-120
  field: lavish 53 / classic 34 / sparse 12.
- **S6 complete** (merged). P3 — the strictly-sequential scene-ledger pass.
  `bake/phases/p3_ledger.py` (`ledger_enter` + `p3_ledger`) registered after P2 on the
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
- Server: `uv run pytest` → **169 passed, 3 deselected** (network + two gpu-live);
  `uv run ruff check .` (server + `tools/`) clean.

## Next up
- **S8** — P5 prompt derivation (`bake/phases/p5_prompts.py`), GPU-LLM, `selected →
  prompts_running → prompts_done`. Unit = selected page (`status: "selected"` only — read from
  `selection.json`). Options per TTS DESIGN §7.5 (ledger from `pages/*.json`, present-cast
  `one_line`s capped at 4 by mention frequency, `era`); artifact `prompts/{page}.json` with
  `derived` verbatim + `edited_prompt: null` + computed `final_subject_prompt`. Plus the CPU-side
  cover pseudo-plate (`prompts/cover.json`) and portrait pseudo-prompts if enabled. Needs 3
  illustration-prompt fixtures. Acceptance: a P0→P5 end-to-end fixture test on the 6-page book.
- **R1** — reader shell/shelf/checkout, unblocked since S3 (build against
  `server/tests/fixtures/bundle/`). **S12** (sync API) unblocked from S1.

## Open questions / blocked
- **Run the live checkpoint when convenient:** on the LAN with TTS T5 up, run
  `TTS_URL=… uv run python ../tools/capture_tts_fixtures.py` to replace the hand-written TTS
  fixtures (cast **and** scene-update) with real captures, and
  `uv run pytest -m gpu test_cast_live.py test_ledger_live.py -s` to paste real cast + ledger
  summaries into `CYCLE-LOG.md`. Not blocking development (fixtures suffice).
- See `NOTES-FOR-NEXT-CYCLES.md` "From S7": `reselect.py` is standalone until a revision re-bake
  wires it (and the "drop never-rendered approvals" reading to confirm); `PageScore` is the
  structural spoiler boundary (P5/P7 read the full ledger from `pages/*.json`, not via selection
  types); the fill-window∩min_gap interpretation; the committed synthetic-120 score fixture.
- See `NOTES-FOR-NEXT-CYCLES.md` "From S6": the trailing-pseudo-unit phase-end-finalize pattern;
  P3 threading (generation uses last-successful ledger, gap inheritance is merge-only); page
  ledgers now live on `pages/*.json` (P4 reads scores from there). "From S5": `cast_running`
  added; the GPU-phase enter pattern; `TtsClient` is the shared GPU-call surface (`unload_models`
  unused until P7); reducer intermediates live in `cast/groups.json`; the major-rule interpretation.
- "From S4/S3" still true: the job record is schema-free runtime state; `job.id == book_id`;
  P0 archival is user-source-only (wire gutenberg archival at M1); `system-overview.md`
  remains absent — treat DESIGN §1/§15 as canonical; paginator inheritances (verse ==
  any-`\n`; separator-ledger round-trip; page-id cap ≤9999).
