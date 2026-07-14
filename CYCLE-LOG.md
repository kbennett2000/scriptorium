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

## R1b — Reader: the reading surface (2026-07-14) — shipped

R1's second half: makes a Resident bundle readable, fully offline. Filled the empty `readerview/`
stub. The load-bearing constraint is byte-faithful rendering — R2's annotation anchors are UTF-16
offsets into exactly this DOM — so the split/join round-trip is locked by test.

**Shipped**
- **`readerview/pagetext.ts`** — pure, DOM-free offset substrate (R2 reuses it verbatim):
  `splitParagraphs`/`joinParagraphs` (exact inverse on the `"\n\n"` delimiter, verse `\n` preserved),
  `paragraphStarts` (`start[i] = Σ len(p_j<i) + 2·i`, UTF-16 code units), `paragraphIndexForChar`
  (restore), `topVisibleChar` (pure, layout-free — ties break to the first paragraph so an all-zero
  jsdom layout → char 0), `throttle`.
- **`readerview/BundleReader.ts`** — the source-agnostic read seam. `StorageBundleReader` (over OPFS
  `Storage`: JSON via `readText`, images via `readBytes` → `Blob({type:image/webp})` → object URL,
  cached + revoked in `dispose()`; maps the logical `images/web/plates/{id}.webp` to the current `-rN`
  on disk by reusing `resolveReaderFiles`/`variantKey`). `FixtureBundleReader` (its own module,
  dynamically imported) inlines the **canonical server fixture** via `import.meta.glob` (`?raw` JSON,
  `?inline` images) — no scriptorium backend, no `fetch` (fence not tripped).
- **Components** (`Reader`/`Page`/`Plate`/`Lightbox`): one logical page = one scrolled unit (ADR-0004);
  chapter-open pages show the chapter title from `structure.json`; **byte-faithful `<p>` per `\n\n`**
  with `white-space: pre-line`; plate at page top → lightbox (Esc/backdrop close, click-zoom); nav via
  ←/→ keys + Prev/Next buttons + swipe + narrow edge tap-zones; **retired plates filtered**
  (`status !== "retired"`). Position `{page_seq, char}` persisted to `positions/{bookId}.json`
  (**outside** `books/`, so Remove keeps it), written on turn / throttled scroll / unmount, restored on
  open.
- **App wiring** — minimal hash route (`#/` shelf, `#/read/{id}` reader, so reload reopens + restores);
  a Resident card gains **Open**; `VITE_FIXTURE_BUNDLE=1` opens the fixture directly; unobtrusive
  "storage protected: yes/no" badge. `vite.config` `server.fs.allow` for the cross-package fixture;
  `VITE_FIXTURE_BUNDLE` declared on `ImportMetaEnv`.
- **Offline-acceptance harness** `reader/scripts/offline-acceptance.sh` — seeds the fixture into a temp
  `library/`, starts the real server, prints the 2-minute human walk.
- Tests: reader **60 vitest** (was 20; +40) — the **rendering-lock** (`join(split)===text` over fixture
  pages + synthetic verse/edge strings, `paragraphStarts` vs `text.slice`, astral-char UTF-16 sanity,
  `topVisibleChar` boundaries, `throttle`); `StorageBundleReader` (`-rN` resolution, object-URL cache +
  revoke, null-for-missing) + `FixtureBundleReader` glob smoke; `Reader` (chapter header, paragraph
  count, **retired-plate hidden**, keyboard/button nav, **only `images/web/**` ever requested**,
  position persist→restore round-trip).

**Decisions**
- **Position is paragraph-granular** (`char` = start of the top-visible paragraph), not intra-paragraph
  interpolated: needs only paragraph tops (testable, reflow-stable, can't bisect a surrogate pair), and
  the schema documents `char` as approximate. Documented in code.
- **All offsets are UTF-16 code units** (`.length`/`.slice`) — no code-point iteration anywhere on the
  offset path, matching the R2 anchor contract (astral chars legitimately count as 2, consistently).
- **Fixture mode reads the canonical server fixture** via glob + one `fs.allow` entry rather than a
  reader-side copy — one source of truth, no drift. `FixtureBundleReader` is dynamically imported so the
  eager glob stays out of the prod bundle (it code-splits to its own 40 KB chunk).
- **Retired-plate note closed:** the plate layer cross-checks `selection.plates[].status`.

**Verification** — reader `npm run lint`/`typecheck`/`test`/`build` all green (**60 vitest**); server
untouched, ruff clean + `uv run pytest` **279 passed / 5 deselected**; `node shared/gen-types.mjs && git
diff --exit-code shared/types` → **no drift** (no schema change). **Fixture-mode smoke:**
`VITE_FIXTURE_BUNDLE=1 vite build` inlines the fixture (JSON into the chunk, webp as local assets); the
dev server serves root, transforms `FixtureBundleReader` (glob resolves pages/structure/images), and
serves the cross-package fixture image via `/@fs` (200, `fs.allow` working). **Offline acceptance
(human-pending, browser-only):** run `reader/scripts/offline-acceptance.sh`, then Download → kill server
→ Open → page-turn across the chapter boundary → plate + lightbox → reload → position restored, network
tab idle. Evidence/screenshots to be pasted here after the human walk.

## R1a — Reader: storage shell + shelf + checkout (2026-07-14) — shipped

First reader cycle. R1 (size L) was split at the plan gate (user-approved): **R1a = the offline-first
plumbing**; R1b (next) = the reading surface. The seam: R1a leaves a bundle **Resident** in local
storage; R1b reads it. Filled the S1 reader scaffold's empty `shell/`/`shelf/` stubs.

**Shipped**
- **`shell/`** — the platform seam (DESIGN §13, ADR-0006). `Storage` interface (`readText/readBytes/
  writeText/writeBytes/exists/delete/list`, binary+text, POSIX paths); `OpfsStorage` (real, over
  `navigator.storage.getDirectory()`); `MemoryStorage` (tests); `CapacitorStorage` (R5 stub that
  throws); `Platform.persistHint()` → `BrowserPlatform` (`navigator.storage.persist()`); `getStorage`/
  `getPlatform` factories. On-device layout `books/{id}/…` + `manifest.local.json`; annotations live
  outside `books/` so Remove keeps them.
- **`shelf/resolve.ts`** — the **`-rN` resolution TS port** (bit-for-bit from `library/checkout.py`):
  `matchesAny`/`variantKey`/`resolveReaderFiles`/`resolvedTotalBytes`, highest-`-rN`-wins, JSON passes
  through, manifest order preserved.
- **`shelf/client.ts`** — the reader's only network module (besides `sync/`, R3). `HttpLibraryClient`:
  `reachable()` (2 s `/health` ping, 60 s cache), `fetchLibrary`/`fetchManifest`/`fetchFileBytes`;
  `ApiError`; base URL same-origin, `VITE_SERVER_URL` dev override.
- **`shelf/checkout.ts`** — the checkout state machine. `sha256Hex` (WebCrypto); `checkout` (fetch
  manifest → `resolveReaderFiles` → skip-if-resident-and-valid, else fetch → sha256-verify → write;
  **retry only the failing file**; write `manifest.local.json` last → Resident; `persistHint` on first
  checkout); `bookState` (Available/Resident/Incomplete, incl. partial-download detection); `delta`
  (fetch changed/new resolved files by path+sha256, prune superseded); `remove` (delete `books/{id}`,
  keep annotations).
- **ESLint network-boundary rule** (`eslint.config.js`) — bans `fetch`/`XMLHttpRequest`/`WebSocket`/
  `navigator.sendBeacon` in `src/**` except `src/shelf/**` + `src/sync/**` (the §13 zero-online-read
  fence, mechanically enforced).
- Minimal shelf UI (`App.tsx`/`Shelf.tsx`/`index.css`) — dense/functional (skin is R4): reachability-
  guarded listing, Resident/Available cards, download-with-progress, Remove-with-confirm.
- **Test stack** mirrored from admin-ui (vitest 2.1 + jsdom + testing-library; `test: vitest run`).
- Shared anti-drift vector `shared/test-vectors/rn-resolution.json` consumed by **both**
  `reader/src/shelf/resolve.test.ts` and the new `server/tests/test_rn_vectors.py`.
- Tests: reader **20 vitest** (storage contract; the shared `-rN` vector; checkout incl. **corrupt→
  retry-only-that-file→complete**, incomplete→resume, delta fetch+prune, remove-keeps-annotations;
  **ESLint boundary fires outside shelf/sync, passes inside**). server **279 passed** (+6 vector cases).

**Decisions**
- **`-rN` drift guard is a shared JSON vector, not a duplicated assertion.** One file drives the
  Python and TS suites; divergence reddens one of them. (NOTES From S11 asked for exactly this.)
- **OpfsStorage is unit-tested only via the Memory contract** — jsdom has no OPFS, so the interface
  semantics are pinned against `MemoryStorage`; real OPFS is exercised in R1b's browser offline run.
- **Checkout is resumable by construction** — verify-and-skip means an interrupted/corrupt download
  leaves the book Incomplete and a re-run fetches only what's missing/wrong; `manifest.local.json`
  written last is the atomic Resident marker.
- **Split executed:** `VITE_FIXTURE_BUNDLE` zero-server dev mode + the reading surface + byte-faithful
  render + plates + position tracking + full offline acceptance are **R1b** (this cycle has no reading
  surface yet — a Resident book shows "Resident ✓").

**Verification** — reader `npm run lint`/`typecheck`/`test`/`build` all green (20 tests); server ruff
clean, `uv run pytest` **279 passed / 5 deselected**; `node shared/gen-types.mjs && git diff
--exit-code shared/types` → no drift (the new vector lives under `shared/test-vectors/`, not
`shared/schemas/`). **Live smoke** (real `uvicorn` over the seeded fixture): the reader's three client
targets all answer — `/health` 200, `/api/library` lists "The Winter Quay" (`total_bytes_reader`
41812), manifest carries the `reader_required` globs, file serving returns `image/webp` + a sha256
ETag. The in-browser OPFS `Download → Resident` needs a real browser (OPFS is browser-only) → left as
a manual step for R1b's browser session; the vitest checkout suite covers the algorithm end-to-end.
Note: TypeScript resolved to 5.9.3 (from `^5.6.3`), whose `Uint8Array<ArrayBufferLike>` generics
required copying bytes into a fresh `ArrayBuffer` before WebCrypto/OPFS writes, and a local
`entries()` narrowing for `FileSystemDirectoryHandle`.

## S12 — Sync API (annotations, positions, backups) (2026-07-13) — shipped

The mutable layer: the DESIGN §12 sync surface that the reader syncs annotations and reading
positions to. Completes the server for M1 — everything after is reader work.

**Shipped**
- `sync/merge.py` — pure, FastAPI-free merge. `merge_annotations` (union by `id`, LWW by `modified`
  via ISO string compare; tombstones merge identically; output canonicalized — dedup-by-id + sorted
  by id — so the algebra is provable by `==`). `merge_positions` (`furthest` = tuple-max on
  `(page_seq, char)` ignoring time; `current` = LWW by `modified`). Ties broken by full-field keys so
  both are truly commutative. `TOMBSTONE_RETENTION_DAYS = 180` documented; compaction deferred.
- `sync/api.py` — `GET /api/users`; annotations GET/PUT and positions GET/PUT under `/api/sync`.
  PUT flow: validate body (422 on fail) → identity-vs-path check for annotations (400) → per-`(user,
  book)` `asyncio.Lock` → merge → validate merged → atomic write (tmp + `os.replace`, the `job.py`
  idiom) → **annotations only:** timestamped backup + prune to newest 20. `{user}`/`{book}` are
  pattern-validated (the traversal guard) plus an `is_relative_to(sync_dir)` backstop.
- `users/loader.py` + committed `users/users.sample.json` (kris/amy/junior). `GET /api/users` reads
  `data_dir/users.json` if present, else the sample; both validated against the `users` schema.
- `config.py` — `sync_dir` + `users_file` properties (derived from `data_dir`; no new fields, no env).
- `app.py` — `sync_router` included (before the catch-all static `/` mount).
- Tests (+20 → **273 passed** / 5 deselected): `test_sync_merge.py` — the three §12 conflict examples
  as named tests + a **seeded-random property harness** (`random.Random`, no `hypothesis`): 800
  annotation triples proving commutative/associative/idempotent, 800 position triples proving the
  same + `furthest` never regresses; **1600 property cases**, every generated & merged doc
  schema-validated. `test_sync_api.py` — users fallback/override/malformed-surfaced; annotations
  union-merge + LWW; **backup prune 25→20 ordered**; invalid-body 422 (nothing written); identity
  mismatch 400; bad-id 400 + encoded-`..` rejected-and-no-leak; positions 404-when-absent +
  furthest-wins; **concurrency: two interleaved async PUTs (httpx `ASGITransport` + `asyncio.gather`)
  keep both annotations** — the lock's proof.

**Decisions**
- **Merge tie-breaks are part of the contract.** LWW "greater `modified`" is ambiguous when two
  copies share a timestamp; each merge key appends a deterministic full-field tiebreak
  (annotations: canonical JSON of the entry; `current`: `(page_seq, char, device)`) so the result is
  independent of argument order — otherwise commutativity fails on equal-timestamp collisions. Caught
  by the property harness while writing it (positions `current` differing only by `device`).
- **Positions GET is 404 when absent, not a synthesized default** (confirmed with the human): a
  positions doc's `page_seq` is ≥1, so there is no valid "empty" value to invent; the reader treats
  404 as "no position yet, start at page 1."
- **Backups are zero-padded `time.time_ns()` filenames** (lexical order == chronological), bump-`+1`
  on the astronomically unlikely same-ns collision. Prune = `sorted(glob)[:-20]` unlinked. Positions
  get no backup (DESIGN §12).
- **users.json dev sample lives in the package** (`users/users.sample.json`) as a loader fallback, so
  a fresh box and the tests get profiles without seeding; a real `data_dir/users.json` overrides it.

**Verification** — ruff clean; `uv run pytest` 273 passed / 5 deselected; admin-ui lint+typecheck+
test green (untouched); `node shared/gen-types.mjs && git diff --exit-code shared/` → no drift (no
schema changes); live smoke (real `uvicorn`, temp data dir): `GET /api/users` sample; two annotation
PUTs merge to `{a,b}` with 2 backups written; positions PUT round-trips; fresh positions → 404;
encoded `..` → rejected (404 via ASGI path-normalization on a real server; 400 via the pattern guard
under TestClient — both safe, nothing escapes `sync_dir`).

## S11 — Library + checkout API (2026-07-13) — shipped

The bridge from a published bundle to the reader: the DESIGN §11.1 library group, the two static
mounts S9b left unwired, and the `-rN` variant-resolution the S10b NOTES deferred here. After this
cycle a published bundle is fully checkout-able; S12 (sync) and R1 (reader eats a real bundle) unblock.

**Shipped**
- **`library/api.py`** (`APIRouter(prefix="/api/library")`, wired in `app.py`) — three read-only,
  unauthenticated (ADR-0005, LAN trust) endpoints, served **only** from `cfg.library_dir` (`work/`
  is never reachable):
  - `GET /api/library` — shelf listing `{id, title, author, cover_thumb_url, revision,
    total_bytes_reader}`. Best-effort dir scan (a malformed/incomplete bundle dir is skipped, not
    fatal). `total_bytes_reader` is the **resolved** reader set (see below).
  - `GET /api/library/{id}/manifest` — `manifest.json` verbatim (the full additive ledger, all
    `-rN` variants); 404 on unknown id.
  - `GET /api/library/{id}/files/{path}` — **path-traversal guard** (`.resolve()` +
    `is_relative_to` → 400, the `review_api.plate_image` idiom), **ETag = sha256** (from the
    manifest; hash-on-the-fly fallback for untracked files), **`If-None-Match` → 304**, content-type
    by extension (json/webp/png).
- **`library/checkout.py`** — the pure, FastAPI-free `-rN` resolution: `resolve_reader_files(manifest)`
  expands the `reader_required` globs then collapses each image variant group `(parent, base_stem,
  ext)` to its **highest `-rN`** (base = revision 1); `resolved_total_bytes()`. JSON files pass
  through untouched. Importable by the scripted-client test; the TS reader mirrors the convention.
- **Static mounts** (`app._mount_static`) — admin-ui `dist/` at `/admin`, reader PWA `dist/` at `/`
  (catch-all mounted **last** so `/api/*` + `/health` win). A dist dir that doesn't exist (tests/CI)
  is skipped silently. New `Config.reader_dist`/`admin_dist` (defaulted; env
  `SCRIPTORIUM_READER_DIST`/`SCRIPTORIUM_ADMIN_DIST`). Closes the S9b "static mount unwired" note.
- **Tests** (+16): `test_checkout_resolve.py` (glob dialect; base-only; highest-of-r2/r3;
  full-res-png-excluded; cover/portrait + web/thumb variants collapse independently) and
  `test_library_api.py` (listing shape; incomplete-dir skip; manifest verbatim + 404; content-types;
  **path traversal rejected** — 3 encoded `%2e%2e` attacks, secret planted in `work/` never leaks;
  ETag=sha256 + 304 flow; the **scripted-client checkout contract** — fetch manifest + every resolved
  file, verify each sha256, transfer == resolved total == listing total; **`-rN` fetch set** via a
  real `regen_published_plate` → exactly one web + one thumb per plate, the `-r2`, base still in
  manifest, `verify_bundle` green). Offline **253 passed / 5 deselected**.

**The `-rN` resolution design call**
Highest-`-rN`-wins, resolved by the library layer as a **documented convention + Python reference
impl**, not a schema field or new endpoint (the prompt `render` block is `additionalProperties:false`
— no current-variant pointer exists). The manifest stays the full additive ledger; `verify_bundle`
and §4.4 immutability are untouched. `GET /api/library` reports `total_bytes_reader` over the
**resolved** set (what the reader downloads); for the fixture (a clean first publish, no variants)
this equals the stored `41812`, so **no P8 change, no fixture regen**. It diverges from the stored
manifest field only after a regen (the stored field still counts the superseded base) — reconciling
P8's stored total is a NOTES follow-up.

**Live acceptance (green)**
Ran a real `uvicorn scriptorium.app:app` over a seeded fixture library and drove the scripted client
against it over HTTP (localhost, in lieu of a second LAN box):
- `GET /api/library` → the one book, `total_bytes_reader: 41812`.
- Fetched manifest + all **18** resolved reader-required files: **every sha256 matched the
  manifest**; total transfer **41812 bytes == resolved total == listing total_bytes_reader**.
- `curl` evidence: `ETag: "6158…fa9f"` + `content-type: image/webp` on a thumb; re-request with
  `If-None-Match` → **304**; encoded `../../work/x.json` traversal → **400** (planted secret never
  served).

**Decisions**
- Resolution is convention-level (highest-`-rN`), not a schema/endpoint change — see above.
- Static dirs are mounted at import time from env; missing dirs skip silently so the test/CI import
  (no `dist/`) is unaffected while dev/prod serve the built SPAs.
- No auth on the library group (ADR-0005); no schema changes (all fields already existed → no
  gen-types drift).

## S10b — Publish (P8) + bundle verifier + post-publish regen + fixture regen (2026-07-13) — shipped

The publish half of S10 (S10 split at the S10a plan gate). Rendered bakes now become an immutable,
verifiable `library/{id}` bundle: `rendered → published`, a standalone verifier, the additive
post-publish `-rN` regen path, and — finally — a fixture bundle produced by the *real* pipeline.
After this cycle the bakery is complete; only S11 (library/checkout serving) stands between a
published bundle and the reader.

**Shipped**
- **`Config.library_dir`** (`data/library/{book_id}/`, §3/§4.2) — the immutable published root.
- **`bake/phases/p8_publish.py`** — `Publish` (CPU rest→rest `rendered → published`, like P4;
  registered after `Render()` in `BAKE_PIPELINE`). One idempotent unit: **integrity guard** →
  **assemble** → **meta** → **manifest**.
  - *Integrity guard (§4.4):* if `library/{id}/pages/*` already exist, every one must be
    byte-identical to the new bake's or publish raises `PipelineBug` (job `failed`) — published page
    text is frozen forever (annotation anchors depend on it). First publish has nothing to guard.
  - *Assemble:* copies `structure/pages/cast/selection/prompts` + `images/**` from `work/` into
    `library/` — **excluding** the `*.src.sha256` derivative sidecars and **not** copying `ledgers/`
    (its merged form rides on `pages/*`). `retired` plate files are copied like any other (additive).
  - *meta.json* is **built** at publish from `job.bake_config` (identity) + computed `stats` +
    pinned `bake` provenance. Pinning is **best-effort + offline-safe**: `pipeline_version` =
    `git describe` (fallback `"unknown"`), `transform_service`/`models` fetched from TTS when
    reachable, else non-empty placeholders (schema requires `minLength ≥ 1`; tests assert shape, not
    values). `revision` = prior library revision + 1, else 1.
  - *manifest.json* via a reusable `build_manifest()` (per-file sha256 + bytes, the 7
    `reader_required` globs verbatim, `total_bytes_reader`) — ported from `make_fixture_bundle`.
- **`tools/verify_bundle.py`** — standalone + importable (`verify_bundle(dir) -> list[str]`, nonzero
  CLI exit). Checks manifest↔disk (hash/size/no-unlisted), every schema, `reader_required` presence,
  and cross-refs (selection↔pages, each non-retired plate + cover + portraits have prompt + image
  trio, retired files kept), tolerating post-publish `-rN` variants. Asserts schema + cross-refs,
  **not** value equality (the fixtures deliberately diverge, per NOTES From S7/S8).
- **Post-publish regen (the `-rN` design call):** the S10a `POST …/plates/{id}/regen` endpoint's
  published branch now calls `regen_published_plate()` — renders a new `…/{page}-rN.png` (+ web/
  thumb) **beside the untouched original** (N = the new revision, first → `-r2`, matching §10),
  updates `prompts/{id}.render`, bumps `meta.revision`, and rebuilds the manifest **in place** — no
  full re-publish, so the integrity guard is never at risk (pages untouched). Reuses the render core
  (`render_to_spec`, factored out of `render_plate`). How the reader picks the current variant
  (highest `-rN` wins) is an S11 concern — no schema change here.
- **Fixture bundle regenerated via the real pipeline.** `tools/make_fixture_bundle.py` now drives a
  genuine P0→P8 offline (real phases, respx TTS, FakeImagegen pixels, real P8) via a shared harness
  `server/tests/_pipeline_build.py` (also the e2e driver). The committed
  `server/tests/fixtures/bundle/` is now real P8 output — clearing the S8-flagged stale prompts
  (`derived.avoid` is now an array, no stray `scene`, §10-correct cover/portrait) and the S7
  hand-written `selection.json` min_gap divergence (it's now genuine P4 output). Byte-reproducible
  (frozen clock + pinned `meta.bake` + deterministic FakeImagegen) → `git diff --exit-code`.
  New identity: `usr-ce8f5ebd29d0` ("The Winter Quay", cast slug `wanderer`).
- **admin-UI** (minimal wiring): `"rendered"` added to `JobStateName` + `CHAIN_ORDER` + the
  Post-render gate + a "Rendered (P7)" milestone; `regenPlate()` client call; the **Regen button is
  enabled** (per-plate re-render, cache-busts the thumb, refetches); the placeholder banner is now
  gated on `render_stub` (added to the review payload) instead of always-on.

**Design call — regen manifest:** in-library additive `-rN` + in-place manifest rebuild (revision
bump), *not* a full republish. Chosen because §4.4 makes revisions additive and only re-publish (a
reselect re-bake, not wired yet) exercises the integrity guard; a single-plate regen never touches
pages, so an in-place manifest update is both sufficient and safe.

**Tests (offline, 237 passed / 5 deselected — was 225/5):** `test_pipeline_e2e` extended to
**P0→P8** (`verify_bundle` green); `test_publish.py` (integrity-guard refusal; republish
idempotency; additive `-r2` regen + verify still green; endpoint published-branch 200); new
`test_verify_bundle.py` (fixture clean + each corruption caught); `test_regen.py` published branch
updated (404-without-library). `test_phases_p4` divergence-doc assertion flipped to a
consistency assertion (the fixture is now real engine output). ruff clean; admin-ui eslint + tsc +
vitest clean; no schema/type drift.

**gpu-marked live render box — PENDING (stale imagegen deploy, reported not papered over):** with
the LAN green (TTS `ollama_reachable:true`, `qwen3.5:9b`; imagegen `comfyuiReachable:true`), the live
render ran end-to-end — TTS unload-first → real SDXL render → derivatives → `rendered`, and TTS
`/health` showed `models_loaded:[]` after (§7.4 sequencing observed). **But plates came back
1024×1024, not 832×1216**: the deployed imagegen-service (pid up ~32.7 h) predates PR #13 — a direct
`POST /generate {width:832,height:1216}` also returns 1024² (HTTP 200, no 422). The fix is already on
disk (`cf0f0a6`, `setNodeSize` present); it needs a service **restart** (`sudo systemctl restart
imagegen-service` on the GPU box — sudo/human, and a shared-service restart I won't do unauthorized).
The gpu-marked `test_render_live` correctly caught the stale deploy (as designed); box stays pending
until the restart. Offline FakeImagegen fully covers development.

## S10a — Real render (P7) + imagegen client + ADR-0011 (2026-07-13) — shipped

The render half of S10 (S10 split at the plan gate; **S10b = publish P8 + verify_bundle**). Approved
shot lists now become pixels: TTS-unload → SDXL render → WebP derivatives, resting at a new
`rendered` state. Publish (`rendered → published`) is S10b.

**ADR-0011 (evidence-first, Task 0).** Read the real imagegen-service API before building. It is a
TypeScript/`node:http` ComfyUI proxy on :8189: `POST /generate` → raw `image/png`; body
`{prompt, negativePrompt?, style?, quality?, seed?}`; `GET /health` → `{comfyuiReachable,…}` (no
busy signal, no load/unload/warmup endpoint). Negative prompts ✅ and seed ✅ — but it emits a
**fixed 1024×1024** with **no width/height param** (hardcoded `EmptyLatentImage` node "5"). DESIGN
§10's 832×1216 was therefore impossible → the mandated stop-and-report. **Product-owner decision
(AskUserQuestion): "Extend imagegen-service"** — a small backward-compatible PR to that repo adds
optional `width`/`height` (default 1024²); scriptorium builds to §10 sizes unchanged.

**Shipped (scriptorium).**
- `docs/adr/0011-imagegen-api.md` — endpoint map, client binding, error→exception mapping, the size
  decision.
- `render/imagegen.py`: `RealImagegenClient` (httpx → `/generate`/`/health`; 503/conn →
  `GpuUnavailable`, 422 → `UnitFailed`, else → `PipelineBug`; unset `IMAGEGEN_URL` → parks). Protocol
  + `FakeImagegen` kept as the shared double.
- `render/derivatives.py`: Pillow WebP (LANCZOS q80) web (≤1080 plate/cover, ≤768 portrait) + 320w
  thumb, **idempotent** via a `{out}.src.sha256` sidecar (skip when source unchanged).
- `bake/phases/p7_render.py` (deletes `p7_render_stub.py`): `RenderEnter` (`approved → rendering`,
  CPU) + `Render` (`rendering → rendered`, GPU). Render's **leading `__unload__` unit** calls TTS
  `unload_models()` (require success) then imagegen `health()` — either failure → `waiting_gpu`, so
  TTS is always freed before SDXL (§7.4/ADR-0009). Per-plate: style-wrap (`prefix+subject+suffix`,
  `negative = style.negative + avoid`; cover/portrait pre-wrapped by P5 pass through), render at the
  §10 size into the §4.2 bundle layout (`images/plates|cover|portraits`), derivatives, and
  `wrapped_prompt`/`negative_prompt`/`render` provenance onto `prompts/*.json`; page plates flip
  `selection.status → rendered`. Client is **injected** (`Render(client=…)`) — no hardcoding.
  Registered in `BAKE_PIPELINE`.
- New `JobState.RENDERED` (approved deviation; precedent S5 `cast_running`) so the enter/GPU split
  has an intermediate state; `test_job_states` updated (`rendering → rendered → published`).
- Regen endpoint `POST …/plates/{id}/regen` (review_api): pre-publish single-plate re-render with a
  fresh seed via a shared `render_plate()`; **409 if published** (the additive `-rN` post-publish
  path is S10b). Client injected via `_imagegen_client` seam.

**Shipped (imagegen-service, separate PR #13).** `POST /generate` gains optional `width`/`height`
(int, multiple of 8, [256,2048], else 422) applied to node "5", default 1024². Backward-compatible;
`tsc` clean; `npm run test:unit` 36 pass; `process.env` still absent (ADR-0001).

**Tests.** Offline **225 passed / 5 deselected** (+11 offline, +1 gpu-live deselected): `test_phases_p7`
(pixels at §10 sizes + derivatives + provenance; unload-before-render ordering; unload-failure parks
`waiting_gpu`; render idempotent), `test_render_derivatives` (sizing + sidecar idempotency),
`test_regen` (new-seed changes pixels + bumps attempts; endpoint 200/409/404), `test_pipeline_e2e`
extended to **P0→P7** (FakeImagegen → `rendered`, artifacts schema-valid), `test_render_live`
(`-m gpu`, pending: renders 2 real plates, asserts 832×1216 + TTS-unloaded-after). ruff clean; no
type drift (schemas already carried `wrapped_prompt`/`negative_prompt`/`render`). admin-ui untouched
(eslint+tsc+vitest still green).

**Deferred to S10b (noted in NOTES).** Publish/manifest/integrity-guard/verify_bundle; fixture-bundle
regeneration; post-publish regen `-rN`; admin-UI Regen wiring + `rendered`-state gate. Also: the live
checkpoint mini-dispatch was **deferred** — TTS reported `degraded`/`ollama_reachable:false` (can't
transform), so live captures/gpu-tests were not run (its own guard says stop-and-report).

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
