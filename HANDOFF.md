# Handoff

## Current state
- **S11 complete** (PR open, awaiting human merge). The library + checkout API — a published bundle
  is now fully checkout-able. New **`library/api.py`** (`APIRouter(prefix="/api/library")`, wired in
  `app.py`, served **only** from `cfg.library_dir`): `GET /api/library` (shelf listing: id, title,
  author, cover-thumb URL, revision, resolved `total_bytes_reader`, best-effort dir scan),
  `GET /api/library/{id}/manifest` (verbatim), `GET /api/library/{id}/files/{path}`
  (path-traversal-guarded → 400, **ETag = sha256** from the manifest, **`If-None-Match` → 304**,
  json/webp/png content-types). New **`library/checkout.py`** — the pure `-rN` resolution
  (`resolve_reader_files`/`resolved_total_bytes`: expand `reader_required` globs, collapse each image
  group to its **highest `-rN`**, base = rev 1; JSON passes through) — the documented
  highest-`-rN`-wins convention (no schema/endpoint change; the reader mirrors it). **Static mounts**
  (`app._mount_static`): admin-ui `dist/` at `/admin`, reader PWA `dist/` at `/` (catch-all last;
  missing dir skipped silently) — closes the S9b "static mount unwired" note. New
  `Config.reader_dist`/`admin_dist` (env-overridable). Offline **253 passed / 5 deselected**;
  ruff/eslint/tsc/vitest clean; no type drift; `verify_bundle` still green. **Live acceptance GREEN**:
  real `uvicorn` + scripted client over HTTP fetched manifest + all 18 resolved reader files (every
  sha256 verified), transfer == `total_bytes_reader` (41812), ETag/304, traversal 400. See NOTES
  "From S11". **Next up: S12 (sync) + R1 (reader eats a real bundle) — dispatchable in parallel.**
- **S10b complete** (merged). The publish half of S10 — the bakery is now
  complete end-to-end (P0→P8). `bake/phases/p8_publish.py`: **`Publish`** (`rendered → published`,
  CPU rest→rest, registered after `Render()`) assembles the immutable `library/{id}` bundle from
  `work/` — **integrity guard** (§4.4: published `pages/*` frozen byte-for-byte or refuse with
  `PipelineBug`), copies artifacts + images (excluding `*.src.sha256` sidecars, not `ledgers/`),
  **builds** `meta.json` (identity from `bake_config` + stats + best-effort/offline-safe `bake`
  pinning), and writes `manifest.json` (reusable `build_manifest`). New **`Config.library_dir`**.
  **Post-publish regen**: the S10a `POST …/plates/{id}/regen` published branch now writes an additive
  `…/{page}-rN.png` (N = new revision) beside the untouched original, bumps `meta.revision`, rebuilds
  the manifest in place (reuses `render_to_spec`, factored from `render_plate`). New
  **`tools/verify_bundle.py`** (standalone + importable; schema + hashes + reader_required +
  cross-refs, tolerates `-rN`). The **fixture bundle is regenerated via the real pipeline** (shared
  harness `server/tests/_pipeline_build.py`, byte-reproducible; new id `usr-ce8f5ebd29d0`) — clears
  the S7 `selection.json` min_gap + S8 stale-prompt divergences. **admin-UI**: `rendered` state added,
  Regen button enabled → `regenPlate`, placeholder banner gated on `render_stub` (added to the review
  payload). Offline **237 passed / 5 deselected**; ruff/eslint/tsc/vitest clean; no type drift.
  **gpu-marked live render box PENDING** — the deployed imagegen-service predates PR #13 (returns
  1024² for an explicit 832×1216 request); needs a `sudo systemctl restart imagegen-service` on the
  GPU box. The live render otherwise ran end-to-end (unload-first observed). See NOTES "From S10b".
- **S10a complete** (merged). The render half of S10 (split at the plan gate). Real P7:
  `bake/phases/p7_render.py` (`RenderEnter` `approved → rendering` + `Render` `rendering →
  rendered`) replaces the S9 stub — a leading `__unload__` unit frees TTS (`unload_models()`,
  require success) then gates imagegen `health()` (§7.4/ADR-0009), then each approved plate
  style-wraps, renders at the §10 size (plate/cover 832×1216, portrait 1024×1024) into the §4.2
  bundle layout, makes idempotent WebP derivatives, and records
  `wrapped_prompt`/`negative_prompt`/`render` on `prompts/*.json`. New `render/imagegen.py`
  `RealImagegenClient` (per **ADR-0011**), `render/derivatives.py`, `JobState.RENDERED`. Client is
  injected (`Render(client=…)`); `FakeImagegen` stays the double. **imagegen-service PR #13** (merged)
  adds optional `width`/`height` to `/generate` (default 1024²). See NOTES "From S10a".
- **S9b complete** (merged). The review-gate **admin UI** — `admin-ui/`
  grown from the blank scaffold into the four §11.3 screens (Books list; New Book wizard; Book
  detail; Review gate; feature-flagged Post-render), wired to the S9a endpoints. **No server
  changes** — every endpoint already existed. Tooling: **Vitest+RTL+jsdom** (offline smoke test,
  stubbed fetch), a Vite dev `server.proxy` → `:8720`, a hand-rolled hash router, a typed fetch
  client + hand-written API types. Plus `tools/seed_review_book.py` (dev helper: seeds a book at
  `prompts_draft` from the fixture bundle for the no-GPU acceptance walk). Chapter editor is minimal
  (no GET-chapters endpoint — see NOTES From S9b); style swatches are placeholder SVG (real samples
  at M1); Regen disabled (S10). **Acceptance box #1 is human-pending** — the real-browser walk; run
  steps below. Frontend-design skill absent again.
- **S9a complete** (merged). The review-gate **server** (S9 was split; S9a = server, S9b = UI).
  `bake/review_api.py` (its own admin router):
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
- Server: `uv run pytest` → **253 passed, 5 deselected** (network + four gpu-live incl. render);
  `uv run ruff check . ../tools` clean. admin-ui: `npm run test` (Vitest) → **1 passed**
  (the offline smoke); eslint + tsc clean. `tools/verify_bundle.py` exits 0 over the fixture bundle.
  imagegen-service (PR #13, merged): `npm run test:unit` → **36 pass**, `tsc` clean.

## Next up
- **S12** — sync API: annotations/positions delta protocol (the second reader-facing group,
  §11.1). The library group (S11) is done; sync is the remaining server surface before the reader is
  fully served. Unblocked from S1.
- **R1** — reader shell/shelf/checkout, unblocked since S3 and now fully unblocked by S11's
  `/api/library/*`. Build against `server/tests/fixtures/bundle/` (a **real** P8 bundle) and a live
  server; the reader can copy admin-ui's test-runner/fetch-client shape but must keep network calls
  fenced to `sync/`+`shelf/`. **Port `library/checkout.py`'s highest-`-rN`-wins resolution** into the
  reader's `sync/` so delta-sync fetches exactly one current image per plate (NOTES From S11).
  S12 and R1 are dispatchable in parallel.
- **Ops (not a cycle):** restart `imagegen-service` on the GPU box so PR #13 (width/height) is live,
  then re-run `pytest -m gpu tests/test_render_live.py` to close the gpu-marked box (832×1216).

## Open questions / blocked
- **gpu-marked render box pending on a stale imagegen deploy (S10b):** the LAN is green and the live
  render runs end-to-end (unload-first observed), but the deployed imagegen-service predates PR #13
  and returns 1024² for an explicit 832×1216 request. Fix on disk (`cf0f0a6`); needs `sudo systemctl
  restart imagegen-service` on the GPU box, then `pytest -m gpu tests/test_render_live.py`. See NOTES
  "From S10b".
- **Run the broader live checkpoint when convenient:** TTS/ollama are healthy now, so
  `TTS_URL=… uv run python ../tools/capture_tts_fixtures.py` can re-capture the TTS fixtures (cast,
  scene-update, illustration-prompt) with real output, and `uv run pytest -m gpu test_cast_live.py
  test_ledger_live.py test_prompts_live.py -s` can paste real summaries into `CYCLE-LOG.md`. Not
  blocking development (fixtures suffice).
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
