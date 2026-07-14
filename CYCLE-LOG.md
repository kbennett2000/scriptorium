# Cycle Log

One entry per executed cycle: what shipped, decisions made, and any inferences.

---

## S1 — Monorepo scaffold, schemas, ADRs (2026-07-13)

**Shipped**
- Repo layout per DESIGN §3: `server/` (uv, Python 3.12, FastAPI), `reader/` and
  `admin-ui/` (Vite + React + TS scaffolds), `shared/` (schemas + generated
  types), `tools/`, `data/`.
- All eleven JSON Schemas in `shared/schemas/` (meta, structure, page, cast,
  selection, prompt, manifest, annotations, positions, users, styles) — draft
  2020-12, `additionalProperties: false` throughout (opaque TTS objects excepted,
  see inferences), `description` on every property.
- Deterministic TS type generation (`shared/gen-types.mjs`,
  `json-schema-to-typescript`) → committed `shared/types/*.d.ts`. Verified: two
  runs produce byte-identical output.
- `server/src/scriptorium/`: `config.py` (env contract), `schemas.py`
  (`validate(kind, obj)`), `app.py` (`GET /health`, degraded-not-500).
- `justfile` (`server-dev`, `reader-dev`, `admin-dev`, `server-test`, `test-all`,
  `lint-all`, `gen-types`).
- ADRs: `0000-template`, `0001`–`0010` transcribed from DESIGN §15; existing
  cycle-model ADR renumbered `0001` → `0012` (0011 reserved for imagegen at S10).
- Seeds: `data/styles.json` (four §9 styles), `CYCLE-LOG.md`,
  `NOTES-FOR-NEXT-CYCLES.md`.
- Tests: `test_schemas.py` (valid/invalid pair per kind, parametrized),
  `test_health.py` (ok / degraded-both-down / degraded-one-down / unconfigured).

**Decisions**
- ADR numbering: DESIGN §15 references ADR-0001…0010 by number throughout its
  prose, so that numbering is authoritative; the project-factory `0001-cycle-model`
  ADR was moved to `0012` to free the slot (confirmed with the human before build).

**Schema-detail inferences** (where DESIGN was abridged or silent, and the schema
had to decide):
- **Opaque verbatim objects vs `additionalProperties: false`.** `page.ledger`,
  `prompt.derived`, and `prompt.render.params_echo` are text-transform-service /
  imagegen output stored *verbatim*; their internal shape is owned by those
  services, not this repo. They are typed as generic `{"type": "object"}` (no
  inner `additionalProperties: false`); the strict `false` is enforced everywhere
  else. This is the one deviation from "additionalProperties:false throughout,"
  and it is deliberate — locking those shapes here would couple us to another
  repo's schema.
- **`meta.source.kind`** enum is `["gutenberg", "user"]` (the bundle-level origin
  class per §5.3), distinct from the admin API request `kind`
  (`gutenberg|text|markdown`), which is not stored in the bundle. `gutenberg_id`
  is optional (present only for gutenberg sources).
- **`bundle_version`** is modeled as `const 1` (v1 schemas validate v1 bundles);
  the field exists to distinguish future formats.
- **`page.ledger` is optional**, not required: published pages carry it, but early
  (P0) work-phase pages are "text only" (DESIGN §7.1), and the same schema
  validates both. Likewise `prompt.wrapped_prompt`/`negative_prompt`/`render` are
  optional (present after render; absent for draft prompts).
- **`cast`** encodes the §4.3 published-contract fields only; reducer intermediates
  (`is_person`, `descriptors` from §7.2) are work-phase and not in `cast.json`.
- **`positions`** has no top-level `book_id`/`user_id` — identity lives in the file
  path (`sync/positions/{user}/{book}.json`).
- **`prompt.page_id`** is a constrained string allowing `NNNN`, `cover`, or
  `portrait-{slug}` (pseudo-plates, DESIGN §10). `selection.plates[].page_id` is
  restricted to `NNNN` (cover/portraits live in `prompts/`, not `selection.json`).
- **`users[].color`** modeled as a CSS hex string (`#rrggbb`); DESIGN §14 says
  only "color". **`styles[].params.steps/cfg`** are nullable (int/number or null),
  null meaning "use imagegen default" (§9).
- **styles.json seed:** the `engraving` strings are verbatim from DESIGN §9; the
  `woodcut`/`watercolor`/`gouache-storybook` prefix/suffix/negative/portrait_prefix
  strings were composed to match §9's one-line descriptions (DESIGN gives full
  strings only for engraving). Tune later if renders warrant.
- **styles.json location:** placed at repo root `data/styles.json` as the committed
  seed (S1 scope wording); at runtime it is copied/loaded into `SCRIPTORIUM_DATA`
  (the repo cannot write `/var/lib`).

**Verification**
- `uv run pytest` → 29 passed. `uv run ruff check .` → clean.
- reader & admin-ui: `npm run lint`, `npm run typecheck`, `npm run build` all green.
- TS gen determinism: two runs byte-identical (sha256 match).

---

## S2 — Ingestion adapters (2026-07-13)

**Shipped**
- `ingest/base.py`: `SourceSpec`, `Chapter`, `RawBook` (frozen/dataclass), the adapter
  registry (`register`/`load`, lazy adapter import to avoid cycles), and the shared
  utilities — `normalize_source_text` (`\r\n`/`\r`→`\n` + NFC), `user_book_id`
  (`usr-`+sha256[:12]), `gutenberg_book_id` (`pg-{id}`), `split_paragraphs`,
  `detect_chapters` (heuristics 1→2→3 in order, first ≥2 wins), `read_source`,
  `archive_source` (→ `work/{id}/source/`).
- `ingest/gutenberg.py`: `search` + `fetch_text` (Gutendex; prefer UTF-8 `text/plain`),
  `strip_boilerplate` (START/END markers, THE/THIS + casing tolerant, missing →
  `boilerplate_unstripped`), `load` (`source.kind: gutenberg`, `spec.text` short-circuits
  the network for offline/sideload).
- `ingest/textfile.py` (`source.kind: user`, no boilerplate strip — §5.1 scopes strip to
  gutenberg) and `ingest/markdown.py` (minimal `---` front-matter parser for
  title/author/language/era; chapter level = first heading level appearing ≥2×).
- `ingest/__main__.py`: dev CLI (`--file/--kind`, `--gutenberg-id`, `--search`).
- `config.py`: added `work_dir` property (`data_dir/work`).
- Fixtures under `tests/fixtures/sources/`: `pg35.txt` (full Time Machine, PG #35),
  `frontmatter.md`, `headerless.txt`, `allcaps.txt`, `pg_markers.txt`.
- `tests/test_ingest.py` (20 tests); `pyproject.toml` gained
  `addopts = "-m 'not gpu and not network'"` so the live `-m network` test is opt-in.

**pg35 result (acceptance eyeball)** — `python -m scriptorium.ingest --file
tests/fixtures/sources/pg35.txt --kind text` → **16 chapters** titled `I`…`XVI`
(heuristic 2, standalone Roman-numeral lines after per-line strip; the Epilogue folds
into `XVI`). Via `--kind gutenberg` the same book yields 16 chapters with the PG license
stripped (`XVI` = 30 paras); via `--kind text` no strip runs, so the trailing license
folds into `XVI` (81 paras) — the intended textfile-vs-gutenberg difference.

**Schema-detail / behavioral inferences**
- **Paragraphs keep internal `\n` verbatim.** Verse stanzas need it (DESIGN §5); prose
  keeps its source hard-wrap, which is harmless because the reader renders prose with
  `white-space: normal` (newlines collapse) and verse with `pre-line`. RawBook stays a
  lossless capture; all reflow is deferred to display.
- **Preamble before the first heading is dropped** when ≥1 heading is found (title page,
  table of contents), so chapters begin at the first real heading.
- **textfile does not strip PG boilerplate** — DESIGN §5.1 scopes stripping to the
  gutenberg adapter. A sideloaded PG file keeps its boilerplate unless ingested as
  `kind: gutenberg`. (Documented; see NOTES.)
- **Markdown front-matter** is parsed by a minimal scalar `key: value` reader (no `pyyaml`
  dep); only title/author/language/era are honored. `RawBook` gained an internal `era`
  field (beyond DESIGN's minimal shape) so a user-supplied era survives to bake config.
- **Chapter titles** are the matched heading text: heuristic-2 titles are the bare Roman
  numeral (trailing `.` stripped, matching structure.json's `"title": "I"`); heuristic-1/3
  titles are the full heading line.

**Verification**
- `uv run ruff check .` → clean. `uv run pytest` → 48 passed, 1 deselected (network).
  `uv run pytest -m network` → 1 passed (live Gutendex, shape-only assertions).
- reader/admin-ui untouched by S2 (remain green from S1).

---

## S3 — Paginator + golden tests + fixture bundle (2026-07-13)

**Shipped**
- `paginate/engine.py`: `paginate(RawBook, params) -> PaginatedBook` (DESIGN §6 steps
  1–7). `PaginationParams(target=550, min=400, max=850)`, `VERSE_CAP=1.25`. Greedy
  whole-paragraph packing; forced sentence-split (`(?<=[.!?…])\s+`, nearest target, via
  `finditer` so the consumed whitespace is captured); verse/`\n`-containing paragraphs
  move whole up to 1.25×max then split on line boundaries; chapters never share a page;
  zero-padded 4-digit ids. Emits `structure.json` and runs `schemas.validate` on every
  page + the structure before returning.
- **Separator ledger** (`ChapterLayout`): every page records the exact separator consumed
  at its leading boundary (`\n\n` between paragraphs, or the split whitespace mid-paragraph),
  so `PaginatedBook.reconstruct_chapter(i)` rebuilds each chapter byte-for-byte **even
  across sentence/line splits** — this is what makes the round-trip guarantee airtight.
- `tools/make_fixture_bundle.py`: deterministic 6-page fake bundle (real P0 pagination +
  hand-written schema-valid meta/cast/selection/prompts + Pillow flat-colour plate/cover/
  portrait PNGs with web/thumb WebP derivatives + manifest with real sha256s). Committed
  under `server/tests/fixtures/bundle/` (30 files, ~196 KB). `/tools/out/` gitignored.
- Fixtures: `sources/verse.md`, `sources/longpara.txt` (one ~3000-word single-line para),
  `sources/submin.txt`, `goldens/pg35.golden.json`.
- Tests: `test_paginate.py` (19 — round-trip, determinism, properties, step-specific,
  golden) and `test_fixture_bundle.py` (7 — schema-validate every file kind, verify every
  manifest hash+size, reader_required present, cross-references).

**pg35 result (acceptance eyeball)** — pg-35 (16 chapters) paginates to **58 pages**.
Per-chapter page counts: `[3,3,3,4,3,4,4,7,4,4,4,5,2,4,1,3]`. Word-count distribution:
min 35 (a short chapter-final page), max 729, mean ≈ 557 — clustered near target 550,
no page under min except chapter-finals, none over the 1.25×max (1062) cap. Golden sample
(page 1 edges): first40 `" Introduction\n\nThe Time Traveller (for s"`, last40
`"ster the perspective of the\nthing. See?”"`. Round-trip byte-exact for all 16 chapters;
two runs byte-identical.

**Decisions / inferences**
- **Normalization composition (§6.6 ∘ S2 `normalize_source_text`):** the paginator does
  **not** re-normalize. `normalize_source_text` already applied NFC + `\n` endings before
  `RawBook` existed and `split_paragraphs` stripped per-line trailing whitespace, so §6.6 is
  satisfied by inheritance: the paginator only concatenates already-canonical strings with
  `\n\n` and *asserts* the invariant on its output (`text == NFC(text)`, no `\r`, no trailing
  whitespace) rather than redoing it. One normalization story, no double-normalize. NFC is
  closed under the codepoint-safe boundaries we split on, so fragments stay NFC.
- **Verse signal = "contains `\n`" (literal §6.5).** Hard-wrapped Gutenberg prose also
  contains `\n`, so both are treated as unsplittable-move-whole. Harmless and correct in
  practice: real wrapped paragraphs are small (they pack fine, never near the cap), while
  paragraphs that actually *need* splitting arrive single-line (no `\n`) and split correctly.
  One rule, no prose/verse classifier. Verified: pg35 packs by whole paragraphs (no splits);
  the single-line `longpara` fixture splits into 6 pages and still round-trips byte-exact.
- **structure title fallback** `chapter.title or raw_book.title or str(index)` (schema
  requires a string); every chapter emits ≥1 page (empty chapter → one empty-text page).

**Verification**
- `uv run ruff check .` (server + tool) → clean. `uv run pytest` → 74 passed, 1 deselected
  (network). Fixture bundle regenerates byte-identically (double-build sha256 match;
  `git diff --exit-code` clean after commit).
- reader/admin-ui untouched by S3 (remain green from S1).

---

## S4 — Job runner + state machine (fake phases) — shipped

**What shipped**
- `bake/job.py` — the `Job` model + the DESIGN §7.3 state machine as a **transition table**
  (`LEGAL_TRANSITIONS`) with a single structural guard `Job.transition` (raises
  `IllegalTransition`). Atomic persistence (`save` = tmp file + `os.replace`) so a kill
  mid-write never corrupts the record. One job per book → `job.id == book_id`,
  `jobs/{book_id}.json`.
- `bake/phases/base.py` — the `Phase` protocol (`units` / `unit_done` via artifact
  existence+parse / `run_unit`), `Unit`, and the three failure classes: `GpuUnavailable`
  (→ `waiting_gpu`), `UnitFailed` (retriable → ladder → `failed_units`), bug-class (→ `failed`).
- `bake/runner.py` — single asyncio worker (directory-scan queue, one job advanced per
  tick), the 3× retry ladder (10/60/300s), the `waiting_gpu` park/resume with Wake-on-LAN
  (`wakeonlan` subprocess, gated by `GPU_WOL_ENABLED`), **per-unit persistence**. `sleep`/
  `wake`/`gpu_gate` are injectable for tests. Started as exactly one task in the app lifespan
  (single-worker + GPU exclusivity are structural, not advisory).
- `bake/api.py` (mounted in `app.py`) — `POST /api/admin/books` runs **P0 inline**
  (`ingest.load → archive_source → paginate → persist work/{id}/pages + structure`, warnings
  surfaced on the job); `GET books`/`{id}`; `PUT books/{id}/chapters` (409 once past
  `ingested`); `POST jobs/{id}/start|pause|resume`.
- Two fake phases + the test suite live under `tests/` (`fake_phases.py`,
  `test_job_states.py`, `test_runner.py`, `test_admin_books.py`).

**State-transition table (implemented)**
```
created          -> ingested | paused | failed
ingested         -> mentions_running | paused | failed
mentions_running -> mentions_done | waiting_gpu | paused | failed
mentions_done    -> cast_done | paused | failed
cast_done        -> ledger_running | paused | failed
ledger_running   -> ledger_done | waiting_gpu | paused | failed
ledger_done      -> selected | paused | failed
selected         -> prompts_running | paused | failed
prompts_running  -> prompts_draft | waiting_gpu | paused | failed
prompts_draft    -> in_review | paused | failed
in_review        -> approved | paused | failed
approved         -> rendering | paused | failed
rendering        -> published | waiting_gpu | paused | failed
published        -> (terminal)
waiting_gpu      -> {its prev GPU running state} | paused | failed   (resume-to-prev only)
paused           -> {its prev active state} | failed                (resume-to-prev only)
failed           -> (terminal)
```
Only the `*_running` + `rendering` states may fall back to `waiting_gpu` (they are the GPU
phases, §7.4). `waiting_gpu`/`paused` store `prev_state` on entry and may resume **only** to
it (or fail) — the resume-to-prev guard is tested as an illegal-transition case.

**Kill-test evidence (load-bearing, `test_kill_mid_unit_resumes_losing_at_most_one_unit`)**
- 5-unit fake phase, worker "killed" mid-`u3` via `CancelledError` (a `BaseException`, so it
  bypasses the bug-class `except Exception` exactly like a real cancellation).
- After the kill: `u0,u1,u2` have checkpoint artifacts + the job persisted at `ingested`
  (phase never reached `to_state`); `u3`'s artifact never landed.
- On restart (fresh phase + runner over the on-disk job): `unit_done` skips `u0,u1,u2`;
  `run_unit` re-executes only `["u3","u4"]`. Work overlap across the kill = `{u3}` → **≤1
  unit lost**.

**Decisions / inferences**
- **The job record is deliberately schema-free.** `jobs/` is gitignored runtime state, not a
  distributed bundle format, so it has no JSON Schema (kept S4 inside the no-schema-edits
  fence). Only P0's `work/{id}/pages/*` + `structure.json` are schema-validated — by the
  paginator itself.
- **P0 runs inline** in `POST /books` (per §11.1), leaving the job at `ingested`; post-P0
  phases are the worker's job. The real pipeline is **P0-only** until S5 registers P1, so a
  *started* job simply rests at `ingested` (honest — no fake phase ships in the package).
- **The tick cadence is the `waiting_gpu` retry interval** — every tick re-gates parked jobs
  with WoL; no separate per-job timer needed.
- **`sleep`/`wake`/`gpu_gate` are constructor-injected** (default real impls) so tests use
  no-op sleeps + fake gates without monkeypatching module globals.

**Verification**
- `uv run ruff check .` → clean. `uv run pytest` → **107 passed, 1 deselected** (network).
  Transition table (legal + illegal) green; flaky recover + exhaust→`failed_units` green;
  `waiting_gpu` via both the health gate and a mid-phase `GpuUnavailable` green; WoL guard
  green; kill-test green; `POST /books` (frontmatter.md) → schema-valid `work/{id}` pages +
  structure. reader/admin-ui untouched (green from S1).

## S5 — TTS client + P1 mentions + P2 reduce/canonicalize (2026-07-13) — shipped

First real GPU phases. `bake/tts_client.py` (async client for `POST /v1/transform/{name}` +
`/v1/models/unload` + `/health`, mapping the TTS §8 error taxonomy to phase-control
exceptions), `bake/reduce_cast.py` (the §7.2 reducer as a pure function), and the four phase
classes that fill the runner's `pipeline=[]` seam. Developed against hand-written TTS
fixtures (TTS unreachable from this box); `tools/capture_tts_fixtures.py` re-captures them
on-LAN.

**Pipeline registered (keyed by `from_state`, each a legal single edge):**
```
mentions_enter    ingested        -> mentions_running   CPU, 0 units (claims the GPU state)
p1_mentions       mentions_running-> mentions_done      GPU, unit=page   -> mentions/{page}.json
p2_reduce         mentions_done   -> cast_running        CPU, 1 unit      -> cast/groups.json + cast.json
p2_canonicalize   cast_running    -> cast_done           GPU, unit=major  -> cast/canon/{slug}.json, cast.json
```
`mentions_enter`/`p2_reduce` are the CPU steps that move a job onto a `*_running` GPU state,
because the runner may only park on `waiting_gpu` from a state in `GPU_STATES`.

**DESIGN deviations (both approved this cycle):**
1. **Added a `cast_running` GPU state** (chain: `… mentions_done → cast_running → cast_done …`;
   `cast_running ∈ GPU_STATES`). §7.3 omitted a running state for P2, which would have left
   its `cast-canonicalize` (a GPU call) unable to park on `waiting_gpu`. With `cast_running`,
   P2's canonicalize parks exactly like every other GPU phase. `mentions_done → cast_done` is
   no longer a direct edge; `test_job_states.py` updated accordingly.
2. **Pronoun-drop in the reducer** (§7.2 amendment): mentions whose normalized name is a bare
   pronoun (`i, he, she, they, we, you, it`) are dropped before grouping — live T5 outputs
   surfaced unattributable first-person `"I"` mentions. Proved by
   `test_bare_pronouns_dropped_before_grouping` + the `"I"` mention in fixture page 0001.

**TTS error taxonomy → job outcome (tts_client, TTS §8):** 503/connection → `GpuUnavailable`
→ `waiting_gpu` (retried each tick w/ WoL); 422 → `UnitFailed` → 3× 10/60/300s ladder →
`failed_units` (unit left un-enriched, cast.json stays valid via nullable
`visual_description`); 400/404/413/401/500 → new `PipelineBug` → bug-class → job `failed`.
Every code is exercised in `test_tts_client.py`; the job-level effect of the representative
codes is exercised end-to-end in `test_phases_cast.py`.

**Reducer (`reduce_cast`, pure) — §7.2 steps implemented + edge tests green:** Weena/Eloi
co-occurrence guard (union skipped if it would co-locate a distinct-on-a-page pair, checked
against component roots so it holds transitively); Mr. Hillyer/Hillyer honorific merge (rule
2c on content tokens); possessive `'s` strip; ≥3-pages **or** top-6 major rule (both
"larger set" branches tested); kebab slug uniquing with `-2` suffixes.

**Fixtures:** `server/tests/fixtures/tts/cast-mentions/{0001..0006}.json` +
`cast-canonicalize/{time-traveller,weena}.json` — **hand-written** (provenance in the
fixtures README), full `{output, meta}` envelopes, schema-shaped to the TTS transforms. The
full P1→P2 run over them yields a schema-valid `cast.json` with `time-traveller` major and
aliases including "the Traveller" (asserted by membership, not exact strings).

**gpu-marked live test** (`test_cast_live.py`, `-m gpu`, skipped offline): P1+P2 over the
first 10 pg35 pages against real TTS; prints a cast summary to paste here. **Not yet run** —
TTS was unreachable from the authoring box; run on-LAN with `TTS_URL` set and paste the
summary on the next live checkpoint.

**Verification:** `uv run ruff check .` (+ `tools/`) → clean. `uv run pytest` → **137 passed,
2 deselected** (network + gpu-live). New: `test_tts_client` (every error code), `test_reduce_cast`
(6 named edge cases + non-person + majority), `test_phases_cast` (full P1→P2 schema-valid
cast.json; resume skips done pages; P1 503 → waiting_gpu → resume; P2 503 → waiting_gpu on
`cast_running`; canonicalize 422 → `failed_units` + null major, phase completes; mentions 400
→ job `failed`), `test_job_states` updated for `cast_running`. reader/admin-ui untouched.

## S9b — Admin UI review-gate workbench (2026-07-13) — shipped

The UI half of S9: `admin-ui/` grown from a blank scaffold into the four §11.3 screens, wired to the
S9a endpoints. Makes invariant #4 ("no plate rendered before a human approves") real for an
operator. **No server changes** — every endpoint already existed (verified against `bake/api.py` +
`bake/review_api.py`).

**Shipped**
- **Tooling.** Test stack chosen fresh (none existed in the repo): **Vitest 2.1 + @testing-library/
  react 16 + user-event 14 + jest-dom 6 + jsdom 25**, explicit imports (no globals). Vite dev
  `server.proxy` `/api`+`/health` → `:8720`; a `test` block in `vite.config.ts` (via `vitest/config`).
  `justfile`: `admin-test`, `admin-build`; `test-all` now runs `admin-test` too.
- **API layer** (`src/api/`): `client.ts` (typed fetch wrapper; `ApiError{status,detail}` so screens
  special-case the approve 422 / gutendex 502 / review 409) and `types.ts` (hand-written `Job`,
  `ReviewPayload`, `GutendexResult`, `CreateBookBody`, `ApproveError`; nested bundle shapes
  re-exported from `@scriptorium/shared`).
- **Router**: a hand-rolled hash router (`routes.ts`) — a `Route` discriminated union, no
  `react-router` dependency (executor's call; keeps the workbench dep-free). Shell in `App.tsx`,
  one dense stylesheet `index.css`.
- **Screens** (`src/features/`): **BooksList**; **NewBookWizard** (Gutendex/paste/upload → metadata
  + era → style picker with placeholder inline-SVG swatches → density → portraits → `POST /books`);
  **BookDetail** (milestone progress, warnings/failed_units/prompt_warnings, pre-P1 chapter editor,
  start/pause/resume, links to Review/Post-render); **ReviewGate** (`PlatesTable` with inline-
  editable prompts + include toggles + beats + per-row prompt_warnings + cover/portrait pseudo-
  plates; `CastPanel` editable with `edited_by_human` badge; density re-select; **Approve** with a
  plate-count confirmation and a **422 refusal that names the promptless pages**); **PostRender**
  (feature-flagged `POSTRENDER_ENABLED`, stub thumbs via `plate-image`, **disabled Regen** — the
  endpoint is S10).
- **Dev seed helper** `tools/seed_review_book.py` — materializes a book at `prompts_draft` from the
  committed fixture bundle (statuses reset to `selected`, images omitted so the stub renders fresh)
  so the **no-GPU** browser walk works on a box with no TTS.
- **Smoke test** (`src/test/smoke.test.tsx`): wizard → create → detail → review → edit prompt →
  toggle plate → approve, entirely on a stubbed `fetch` (offline). The automated half of box #1.

**Decisions**
- **Hand-rolled router**, not react-router — five destinations don't justify a dependency in a
  workbench; hash routing deep-links and refreshes fine (jsdom fires `hashchange`, so the smoke test
  exercises real navigation).
- **Test stack** Vitest+RTL+jsdom with explicit imports (no `globals:true`), so eslint/tsconfig need
  no globals wiring. Playwright deferred.
- **Chapter editor is minimal** (a raw chapters-JSON re-submit) because there is **no admin endpoint
  to READ current chapter paragraphs** — only `PUT …/chapters` to replace them. A richer editor
  waits on a GET-chapters endpoint (filed in NOTES From S9b).
- **Style swatches are placeholders** (deterministic inline SVG from the style id). DESIGN §11.3
  wants committed static samples — deferred to M1.
- **No static `/admin` mount** (that's a server change); dev uses the Vite proxy. `admin-ui/dist/` is
  gitignored.

**Verification**: eslint + tsc clean; `vitest run` → 1 passed; `npm run build` OK; ruff clean
(server + `tools/seed_review_book.py`); server pytest unchanged (**214 passed / 4 deselected** — no
server code touched); `git diff --exit-code` clean after `gen-types` (no schema edits).

**Box #1 (human-pending)**: verified the no-GPU path works via TestClient against a seeded book
(review 200 → 3 plates + cover/portrait prompts → approve 200 → `approved`). The **real-browser**
walk is human-pending; run steps for both paths are in HANDOFF / the plan file.

The **frontend-design skill was again absent** in this environment — density/restraint applied
directly.

## S9a — Review-gate server + demo P7 stub (2026-07-13) — shipped

The server half of S9 (the review gate). Surfaces the `prompts_draft` shot list for a human, lets
them edit prompts/cast and add/drop plates, re-turn the density knob, and **approve** — the gate
that makes invariant #4 ("no plate rendered before approval") real. Plus a `FakeImagegen` and a
**demo P7 render stub** so the whole wizard→review→approve→render path is demonstrable now, GPU-free.

**Split decision.** S9 is a size-L cycle. Per the plan gate it was **split S9a (server) / S9b (UI)**,
and per an explicit user choice this session is **S9a only** — the `admin-ui/` screens + a Vitest/RTL
smoke test are deferred to S9b. Acceptance box #1 (full browser run) is an S9b deliverable; its
refusal/persistence sub-tests (boxes #2, #3) land here. The **frontend-design skill is not installed**
in this environment; S9b will apply its principles directly.

**No state-machine / schema change.** The chain already held
`prompts_draft → in_review → approved → rendering → published`. `approve` **walks
`prompts_draft → in_review → approved`** in one call — `in_review` is a transient waypoint in S9a (a
later cycle may surface it as a resting "claimed for review" state). The P7 stub runs
`approved → rendering` and the book **rests at `rendering`** (publish is S10). The only additive
change is a `Job.render_stub: bool` flag (schema-free runtime state, like `prompt_warnings`), set by
the stub so S10/UI know the pixels are placeholders.

**Endpoints** (`bake/review_api.py`, its own `APIRouter(prefix="/api/admin")` included in `app.py`):
`GET /gutendex?q=` (search proxy, trims upstream, degrades to 502 — never 500); `GET /styles`
(the catalog for the wizard picker); `GET /books/{id}/review` (selection + all prompts incl.
pseudo-plates + cast + `prompt_warnings` + `failed_units` + per-page beats; 409 pre-P5);
`PUT …/review/prompt/{page_id}` (persists `edited_prompt`, recomputes
`final_subject_prompt = edited_prompt ?? derived.prompt`); `PUT …/review/selection` (manual
add/remove — a never-rendered remove **deletes the entry but keeps `prompts/{id}.json`** so an
include-toggle round-trips; a rendered remove retires); `PUT …/review/cast/{slug}` (sets
`edited_by_human`); `POST …/approve` (refuses **422** with the offending `page_ids` if any
selected/manual plate lacks a prompt, else flips plates → `approved`); `POST …/reselect`
(§8 re-selection with the new preset, then re-queues P5); `GET …/plate-image/{page_id}.png`
(work-dir PNG serve, path-traversal-guarded, for the S9b post-render thumbs).

**Approve-refusal evidence** (acceptance box #2): `test_review_api.py::
test_approve_refuses_when_a_selected_plate_lacks_a_prompt` manually adds page `0002` (which has no
`prompts/0002.json`) → `POST /approve` returns **422** with `detail.page_ids == ["0002"]` and the
job stays at `prompts_draft` (no partial transition). Box #3:
`test_prompt_edit_persists_and_recomputes` asserts the edit lands on disk and
`final_subject_prompt` recomputes (and reverts to `derived.prompt` when cleared).

**Reselect re-queue reading.** Pre-publish, with nothing rendered and no manual plates, the §8
merge reduces to "the merged plate set == the fresh `select()` output" (never-rendered non-chosen
plates are dropped). The endpoint recomputes `PageScore`s from `pages/*.json`, runs
`select` + `reselect(revision=current_max_added_in_revision)` (no revision bump pre-publish — that
additive flow is S10), keeps prompt files, then **resets `job.state = SELECTED` directly** (a
deliberate pipeline re-entry, not a forward edge; guarded to pre-render states) so the runner
re-runs P5, deriving only the newcomers (P5 `unit_done` skips existing prompts).

**P7 stub seam for S10.** `bake/phases/p7_render_stub.py` is `is_gpu=False` (FakeImagegen is
pure-CPU — no gate/WoL), renders `final_subject_prompt` as-is (no style wrap / negative), writes
`images/plates/{page_id}.png` per drafted plate (pages + `cover`/`portrait-*`), flips page plates
`approved → rendered`, sets `render_stub`, and **rests at `rendering`** — no derivatives, no
manifest, no publish. Its module docstring states the seam: **S10 deletes this file** and lands the
real `p7_render.py` (`is_gpu=True`, enter-split, pre-phase TTS unload, §10 wrap/negative,
derivatives, `rendering → published`). `FakeImagegen` (`render/imagegen.py`, deterministic Pillow
PNG with the prompt hash burned in) is the shared fake S10 keeps.

**Tooling recorded for S9b:** Vitest + React Testing Library + jsdom with a stubbed `fetch` for the
UI smoke test (offline, no browser download); the real pipeline/endpoint flow stays covered by
server pytest. Playwright deferred.

**Verification:** `uv run ruff check .` → clean. `uv run pytest` → **214 passed, 4 deselected**
(+25; network + three `-m gpu` live). New tests: `test_review_api.py` (payload shape + warnings +
beats, prompt edit persist/recompute/404/409, selection remove-keeps-prompt + re-add, add rejects
non-page-ids, cast edit sets `edited_by_human`, approve refusal + lock + 409), `test_reselect_api.py`
(denser adds + re-queues to `selected`, sparser drops never-rendered, guard past approval, unknown
preset), `test_gutendex_proxy.py` (respx trim + 502-not-500 degrade), `test_phases_p7_stub.py`
(placeholders render, page plates → `rendered`, `render_stub` set, idempotent), `test_fake_imagegen.py`
(valid PNG, requested size, determinism). No schema change (no type regen); `reader/` untouched;
no `admin-ui/` code (S9b).

## S8 — P5 prompt derivation (2026-07-13) — shipped

The GPU-LLM phase that derives one `illustration-prompt` per selected page, plus the two
CPU-assembled pseudo-plates (cover + optional portraits), filling the edge
`selected → prompts_running → prompts_draft` with schema-valid draft `prompts/{page_id}.json`
records for the S9 review gate.

**No state-machine / schema change.** `PROMPTS_RUNNING`/`PROMPTS_DRAFT` and their edges already
existed in `_CHAIN`, and `PROMPTS_RUNNING` was already a GPU state. Two phases mirror the
P1/P2/P3 enter/run split: `PromptsEnter` (CPU, `selected → prompts_running`, zero units) then
`PromptsDerive` (`name="p5_prompts"`, GPU, `prompts_running → prompts_draft`). Registered after
`P4Select()` in `app.py`.

**Pseudo-unit placement decision.** The cover and portraits are **trailing CPU pseudo-units** in
the single GPU phase — `PromptsDerive.units()` = the selected pages, then `Unit("cover")`, then
`Unit("portrait-{slug}")` per eligible major (when `portraits_enabled`). This reuses P3's
merge-unit pattern verbatim (non-numeric ids can't collide with a 4-digit page id; they are
reached only after every TTS page unit has succeeded or ladder-failed, and the phase parks on
`waiting_gpu` *before* them on a 503). Cover is always emitted; portraits are gated by config.

**Per-page derivation.** Options per TTS §7.5: `ledger` = the page's merged `pages/*.json` ledger;
`cast` = present-cast (characters whose canonical **name or any alias** is in `ledger.present`),
capped at 4 by `len(mention_pages)` desc, tie → earliest first-mention page, each `{name,
one_line}`; `era` from `bake_config` (omitted if unset). The transform `output` is stored verbatim
as `derived`; `edited_prompt: null`; `final_subject_prompt = derived.prompt`. `wrapped_prompt`/
`negative_prompt` stay absent until P7.

**Two interpretations flagged (documented, following S7's precedent).**
1. **Pseudo-plate `final_subject_prompt` includes the style prefix/suffix (§10 verbatim).** The
   §10 portrait formula bakes `style.portrait_prefix` *into* the prompt, so for consistency the
   cover formula's `style.prefix`/`suffix` are part of the string too. A pseudo-plate's
   `final_subject_prompt` is thus the full §10 formula output (`derived = {"prompt": <string>}`).
   The hand-written S3 `bundle/prompts/{cover,portrait-*}.json` are **stale placeholders** —
   they ignore the §10 frontispiece/portrait formulas and store a *string* `derived.avoid` + a
   `scene` field (contra TTS §7.5's array `avoid` + `{prompt,depicted,shot}`). Tests assert
   schema + cross-references, not equality with them. **For the S10 verify tool:** regenerate the
   bundle prompt fixtures (via `make_fixture_bundle.py`) to the §10 formulas + §7.5 `derived`.
2. **`meta.warnings` recorded defensively.** TTS §4's `meta` does not currently define a
   `warnings` key, but `meta` is an open provenance object. P5 reads `meta.get("warnings", [])`
   via a new `TtsClient.transform_with_meta` and, when non-empty, records it on
   `job.prompt_warnings[page_id]` (new schema-free job field) for S9. Harmless when absent.

**Supporting changes (in scope).** `styles/` gained a loader (`load_styles`/`get_style`,
validates `data/styles.json`, `PipelineBug` on an unknown id — path-resolved like `schemas.py`,
independent of the passed `Config`). `TtsClient` gained `transform_with_meta` via an extracted
`_post` (existing `transform` behaviour byte-identical — P1/P2/P3 untouched). `Job` gained
`prompt_warnings: dict[str,list[str]]`. `tools/capture_tts_fixtures.py` now also threads
`illustration-prompt` over the captured pages for on-LAN re-capture.

**Sample assembled cover string** (engraving style, §10 formula):
`19th-century steel engraving book illustration, fine crosshatching, monochrome ink, dramatic
light, frontispiece for the book 'The Tidewatch Fragment' by A. Fixture: a quiet harbour at dawn,
intricate linework, aged paper tone, high detail`

**Regression anchor.** `test_pipeline_e2e.py` runs real **P0 → P5** on a committed inline synthetic
book (paginates to 6 pages / 1 chapter → P4 tiny-work selects 2 plates), driving the registered
`BAKE_PIPELINE` with generic schema-valid TTS stubs, then validates every schema-bound artifact
in `work/`: `structure.json`, all `pages/*.json` (with merged ledgers), `cast.json`,
`selection.json`, and all `prompts/*.json` (2 page prompts + `cover` + 1 portrait). This is the
pipeline's standing regression guard from here on.

**Verification:** `uv run ruff check .` (+ `tools/`) → clean. `uv run pytest` → **189 passed,
4 deselected** (network + three `-m gpu` live tests, now including `test_prompts_live.py`). New
tests: `test_prompts_assembly.py` (present-cast filter/cap/tie-breaks, cover/portrait/condense
strings exact vs §10), `test_phases_p5.py` (per-page derive through the runner, cover + portrait
pseudo-plates, `meta.warnings` capture, portraits-disabled, idempotent resume),
`test_pipeline_e2e.py` (the P0→P5 acceptance box), `test_prompts_live.py` (`-m gpu`, pending
on-LAN). 3 hand-written `illustration-prompt` fixtures added. reader/admin-ui untouched; no schema
change (no type regen).

## S7 — P4 selection engine (deterministic) (2026-07-13) — shipped

The pure, deterministic plate-selection function (DESIGN §8) plus its re-selection diff and the
CPU bake phase that turns per-page ledger scores into `selection.json`, filling the last open
pipeline edge `ledger_done → selected`.

**No state/schema/runner change.** `JobState.SELECTED` and the `ledger_done → selected` edge
already existed in `_CHAIN`; `SELECTED` is not a GPU state; `"selection"` is a registered
schema kind. P4 is the pipeline's **first pure rest→rest CPU phase** — `is_gpu=False`, one
`Unit("select")`, sync `run_unit`, **no enter/`*_running` split** (enter phases exist only so a
GPU phase can park on `waiting_gpu`; a CPU phase skips the gate). Registered as `P4Select()` in
`app.py` after `LedgerScenes()`.

**Engine (`selection/engine.py`).** `select(scores, structure, params)` over three frozen
dataclasses — `PageScore` (**numbers + booleans + the page-id only; the spoiler invariant made
structural**, pinned by a test), `Params`, `PlateChoice` — and a `PRESETS` data table (the §8
rows verbatim: lavish 1/3/0.40, classic 2/6/0.55, sparse 4/12/0.85 with scene_boundary off).
Steps: (1) mandatory marks — chapter openers from `structure.chapters[].page_ids[0]` + enabled
scene boundaries; (2) `min_gap` collapse by precedence `chapter_open > scene_boundary` →
salience → earlier seq, via greedy chain resolution; (3) fill; (4) tiny-work `<8 pages →
{page 1} ∪ {argmax}`; (5) reasons. Fully deterministic (no RNG, every tie-break specified),
proven by a repeat-run test.

**Interpretation — fill window ∩ min_gap (documented deviation from a literal read).** §8 step 3
writes the fill window as `(last+1 … last+max_gap)`, but the binding acceptance property is "no
two plates closer than `min_gap`" over *all* plates, including fills — a literal `last+1` lower
bound can violate it. The engine therefore intersects the fill window with the min_gap constraint:
`[last+min_gap, min(last+max_gap, next_anchor−min_gap)]` (tail: up to the last page). For all
three presets `max_gap ≥ 2·min_gap`, so a fill region is always wide enough; the floor is the
only reason a gap is left unfilled ("gaps may exceed max_gap rather than force a weak plate").

**Re-selection (`selection/reselect.py`, standalone).** `reselect(fresh, existing_plates,
revision)`: manual entries pass through untouched; a re-chosen **rendered** plate stays
`rendered` (no re-render, `added_in_revision` preserved); re-chosen `selected`/`approved` keep
their status; re-chosen `retired` revives to `selected`; a new page is `selected@revision`; a
**rendered** plate not re-chosen → `retired` (files kept — additive invariant); `retired` stays
`retired`; a **never-rendered non-manual** (`selected`/`approved`) plate not re-chosen is
**dropped** (no pixels to preserve). That last rule is the one place a human `approved` on an
*unrendered* plate is discarded — a deliberate reading of §8, flagged here for review. The P4
**phase** only ever writes a *fresh* selection (revision 1); wiring `reselect` into a density
re-turn belongs where revisions are bumped (re-bake/publish), outside the S7 runner path.

**Scores read from `pages/*.json`, not `ledgers/*.json`** (the merged, gap-filled view, per
NOTES "From S6"); P4 consumes only `scene_changed` + `visual_salience`.

**Plate counts over the committed synthetic 120-page field** (12 chapters × 10 pages,
`fixtures/selection/synthetic-120.json`, `random.Random(4835)`, committed so tests are
RNG-independent): **lavish 53** (12 chapter_open / 14 scene_boundary / 27 fill), **classic 34**
(12 / 9 / 13), **sparse 12** (12 chapter_open, no scene/fill — chapters are 10 apart < max_gap
12, so sparse resolves to exactly the openers). All presets satisfy the min_gap property; every
fill clears its floor.

**Fixture-pipeline acceptance / divergence note (for the S10 verify tool).** Running P4 over the
S3 bundle book (6 pages, ledgers merged from the S6 `scene-update` fixtures) yields a schema-valid
`selection.json`, but it **legitimately differs** from the hand-written `bundle/selection.json`:
the bundle is 6 pages → tiny-work → `{0001, argmax=0004}`, whereas the hand-written fixture lists
`0001/0003/0004` with `0003` as a `scene_boundary` (the fixture ledger has `scene_changed:false`
at 0003) and `0003/0004` adjacent (a classic min_gap=2 violation). The test asserts schema +
invariants, not equality.

**Verification:** `uv run ruff check .` (+ `tools/`) → clean. `uv run pytest` → **169 passed,
3 deselected** (network + the two `-m gpu` live tests). New tests: `test_selection_engine.py`
(preset properties over synthetic-120 — min_gap, floor, openers present, reasons, determinism;
precedence/salience/seq tie-breaks; tiny-work + dedup; pathological all-low-salience; the
structural spoiler test; schema-valid output), `test_reselect.py` (denser/sparser/overlap/manual/
retired-revive/ordering), `test_phases_p4.py` (phase → schema-valid selection through the runner;
preset from `bake_config`; idempotent skip; the fixture-pipeline acceptance box). reader/admin-ui
untouched; no schema change (no type regen).

## S6 — P3 scene ledger (strictly sequential) (2026-07-13) — shipped

The single sequential `scene-update` pass that produces both the per-page continuity ledger
and the selection scores P4 will consume. `bake/phases/p3_ledger.py` fills the
`cast_done → ledger_running → ledger_done` segment, registered in `app.py`'s pipeline after
P2. **No state-machine change:** `ledger_running`/`ledger_done` were already in the §7.3 chain
and `ledger_running` was already in `GPU_STATES`, so all edges were legal out of the box — S6
logs **no DESIGN deviation**.

**Phase table:**

| Phase (class) | from → to | is_gpu | units | effect |
|---|---|---|---|---|
| `LedgerEnter` | `cast_done → ledger_running` | no | — (zero) | the CPU "enter-running" claim (a GPU phase's `from_state` must be a GPU state) — mirrors `MentionsEnter`/`CastReduce` |
| `LedgerScenes` | `ledger_running → ledger_done` | **yes** | pages in id order **+ trailing `merge` pseudo-unit** | per page → `ledgers/{id}.json` (verbatim `scene-update` output); `merge` → writes `ledger` into every `pages/*.json` with the gap rule |

**Threading semantics (the load-bearing behaviour, stated explicitly):**
- A page's `prior_ledger` is the **last *successful* stored ledger** before it (the greatest
  earlier page-id with a `ledgers/*.json` artifact), else `null` on page 1. Contiguity resume
  falls out for free: the runner iterates units in page order and skips done ones, so a restart
  begins at the first missing ledger and threads from its stored predecessor.
- **Generation never threads from an inherited gap ledger.** If page 3 permanently fails, page 4
  is *generated* threading from page 2 (the last success); page 3's *inherited* ledger exists
  only in the merged `pages/*.json` (provenance), produced by the merge unit.

**Gap rule — applied at phase end, not unit time.** `units()` appends a trailing `merge`
pseudo-unit; the runner reaches it only after every page unit in the pass has succeeded or
ladder-failed, and parks on `waiting_gpu` *before* it if a page 503s. So the gap commit only
happens when the phase genuinely completes — a late retry on an interrupted pass can still fill
the real ledger first. `merge` (pure I/O) iterates pages carrying `prev`: a page with a stored
ledger uses it verbatim; a permanently-failed page inherits a copy of `prev` with
`carry_notes += " [ledger gap]"` (capped at the §7.4 200-char limit); a leading gap gets a
neutral ledger. Each page is `schemas.validate("page", …)`-checked before write. **Why a
trailing pseudo-unit:** the S4 runner has no phase-end hook and is outside the S6 scope fence
(may not be modified), so a trailing unit is the only in-scope way to run a post-units merge.

**`scene-update` options:** `prior_ledger` (as above), `cast_names` = canonical `name`s from
`cast.json` (cap 40), optional `era` from `bake_config`. Failure taxonomy is unchanged (via
`TtsClient`): 503/connection → `waiting_gpu` on `ledger_running`; 422 → `failed_units` (page
left ledger-less, filled by the gap rule); 400/404/413 → job `failed`.

**Fixtures:** `server/tests/fixtures/tts/scene-update/{0001..0006}.json` — **hand-written**
(provenance in the fixtures README), full `{output, meta}` envelopes forming one continuous,
threadable scene run (smoking-room → laboratory → time-jump → 802,701 AD → river → sphinx at
dusk), with `scene_changed: true` on `0004`. `tools/capture_tts_fixtures.py` extended to thread
`scene-update` over 6 pages so an on-LAN run overwrites them.

**gpu-marked live test** (`test_ledger_live.py`, `-m gpu`, skipped offline): threads the first 8
pg35 pages against real TTS and prints a per-page `changed/salience/location` summary. **Not yet
run** — TTS unreachable from the authoring box; run on-LAN with `TTS_URL` set and paste the
summary at the next live checkpoint.

**Verification:** `uv run ruff check .` (+ `tools/`) → clean. `uv run pytest` → **142 passed,
3 deselected** (network + the two `-m gpu` live tests). New `test_phases_ledger.py`: threading
(`prior_ledger` of call N == output N−1, page 1 null); merge writes schema-valid page ledgers
(incl. the `scene_changed:true` round-trip); contiguity resume (skips done, threads from stored
predecessor, ≤1 lost); gap rule (page 3 422 → inherited page-2 ledger + annotation, pages 4–6
real, page 4 generated from page 2); 503 → `waiting_gpu` on `ledger_running` → resume.
reader/admin-ui untouched.
