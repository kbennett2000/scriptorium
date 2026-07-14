# Handoff

## Current state
- **S9a complete** (PR open, awaiting human merge). The review-gate **server** (S9 was split;
  S9a = server, **S9b = admin UI is next**). `bake/review_api.py` (its own admin router):
  `GET /gutendex` search proxy (degrades 502, never 500), `GET /styles`, `GET …/review`
  (selection + all prompts incl. cover/portrait pseudo-plates + cast + `prompt_warnings` +
  `failed_units` + per-page beats), `PUT …/review/prompt/{id}` (persists `edited_prompt`,
  recomputes `final_subject_prompt`), `PUT …/review/selection` (manual add/remove; a
  never-rendered remove drops the entry but **keeps the prompt file** so include-toggles
  round-trip), `PUT …/review/cast/{slug}` (`edited_by_human`), `POST …/approve` (**refuses 422**
  if any selected/manual plate lacks a prompt, else → `approved`), `POST …/reselect` (§8
  re-selection + re-queues P5 for newcomers by resetting state to `selected`),
  `GET …/plate-image/{id}.png`. **No state-machine / schema change** — `approve` walks the
  existing `prompts_draft → in_review → approved` edges; only added `Job.render_stub: bool`.
  Plus `render/imagegen.py` (`ImagegenClient` protocol + deterministic `FakeImagegen`) and a
  **demo** `bake/phases/p7_render_stub.py` (`is_gpu=False`, `approved → rendering`, FakeImagegen
  placeholders, rests at `rendering`) registered in `BAKE_PIPELINE` — **S10 replaces the stub
  wholesale**. Frontend-design skill was absent in this env.
- **S8 complete** (merged). P5 — prompt derivation.
  `bake/phases/p5_prompts.py`: `PromptsEnter` (CPU, `selected → prompts_running`) + `PromptsDerive`
  (GPU, `prompts_running → prompts_draft`). One `illustration-prompt` per `status:"selected"` page
  (options per TTS §7.5: full ledger + present-cast `{name,one_line}` capped 4 by mention
  frequency + `era`); `derived` verbatim, `edited_prompt:null`, `final_subject_prompt=derived.prompt`.
  Cover + portrait pseudo-plates assembled CPU-side per DESIGN §10 as **trailing pseudo-units**
  (`cover` always; `portrait-{slug}` per major with a description when `portraits_enabled`) — their
  `final_subject_prompt` includes the style prefix/suffix per the §10 formulas (P7 must not
  re-wrap them). **No state/schema change** (edge + GPU state pre-existed). Supporting: a
  `scriptorium.styles` loader, `TtsClient.transform_with_meta`, `Job.prompt_warnings` (per-page
  TTS `meta.warnings` for S9). The stale S3 `bundle/prompts/*` fixtures diverge (regenerate at
  S10 — see NOTES From S8). New standing regression anchor: `test_pipeline_e2e.py` (real P0→P5,
  every artifact schema-valid).
- **S7 complete** (merged). P4 — the deterministic selection engine.
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
- Server: `uv run pytest` → **214 passed, 4 deselected** (network + three gpu-live);
  `uv run ruff check .` (server + `tools/`) clean.

## Next up
- **S9b** — the admin UI (DESIGN §11.3), fully unblocked by S9a's endpoints. Screens: Books list;
  New Book wizard (`GET /gutendex` / paste / upload → metadata + era → style picker reading
  `GET /styles` → density → portraits → `POST /books`); Book detail (state/warnings/failed_units,
  pre-P1 chapter editor, job controls); Review (plate table + inline-editable prompts + include
  toggles + editable cast panel + cover/portrait pseudo-plates + Approve w/ count confirm, showing
  `prompt_warnings`); feature-flagged Post-render view (stub thumbs via `…/plate-image`, disabled
  Regen). Tooling: **Vitest + RTL + jsdom, stubbed `fetch`** (Playwright deferred); add a Vite dev
  `server.proxy` → `:8720`; hand-write API-payload types. Acceptance box #1 (full browser run +
  screenshot/recording note) completes here. Full spec at the tail of the S9a plan file + NOTES
  "From S9a".
- **R1** — reader shell/shelf/checkout, unblocked since S3 (build against
  `server/tests/fixtures/bundle/`). **S12** (sync API) unblocked from S1.

## Open questions / blocked
- **Run the live checkpoint when convenient:** on the LAN with TTS T5/T6 up, run
  `TTS_URL=… uv run python ../tools/capture_tts_fixtures.py` to replace the hand-written TTS
  fixtures (cast, scene-update, **and now illustration-prompt**) with real captures, and
  `uv run pytest -m gpu test_cast_live.py test_ledger_live.py test_prompts_live.py -s` to paste
  real cast + ledger + prompt summaries into `CYCLE-LOG.md`. Not blocking development (fixtures
  suffice).
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
