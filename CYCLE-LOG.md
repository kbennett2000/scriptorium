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
