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

## R5 — Capacitor Android + persistence hardening (2026-07-14) — shipped

The reader becomes a phone app. Added Capacitor 7 + the Android platform (iOS scaffolded, deferred);
made the R1a `CapacitorStorage` throwing-stub a real backend; hardened the offline path; and did the
full emulator acceptance. Debug **APK = 4.2 MB**.

**CapacitorStorage** (`shell/capacitor.ts`) over `@capacitor/filesystem` under `Directory.Data`,
mirroring OpfsStorage semantics — UTF-8 text, byte-exact base64 for binary, idempotent subtree-capable
`delete`, recursive `list`. The Storage contract assertions were extracted into a framework-free
`shell/storage-contract.ts#runStorageContract` and now run **three ways**: vitest against MemoryStorage,
vitest against a mocked `@capacitor/filesystem` (`capacitor.test.ts` — pins path-walk + base64 in CI),
and an **on-device self-test** (Settings → "Run") against the real plugin — which returned **PASS** on
the emulator. `getStorage()`/`getPlatform()` now pick the Capacitor backends when
`Capacitor.isNativePlatform()`. `CapacitorPlatform.persistHint()` returns `true` (Directory.Data is
app-private and not OS-evicted; no `navigator.storage.persist` analogue) → Settings shows "protected".

**Native shell** (`shell/native.ts` + `shell/back.ts`, both no-ops on web): a LIFO back-handler stack
routes the Android hardware/gesture Back through close-overlay → previous-page → shelf →
`App.minimizeApp()` (never `exitApp`). Reader registers one handler encoding its overlay priority;
Settings registers its own. Status-bar icon style tracks the theme (`applyStatusBarForTheme`). Top/bottom
bars clear the Android-15-edge-to-edge system bars via CSS `env(safe-area-inset-*)` insets
(`setOverlaysWebView` is ignored on API 35+).

**LAN cleartext (server untouched).** Three independent gates had to fall for the app to reach the
plain-HTTP bakery from the WebView, and the emulator run surfaced each: (1) Android blocks cleartext →
`network_security_config.xml` denies cleartext by default and allowlists only the bakery host(s)
(`10.0.2.2`, the household LAN IP) — Android NSC can't express RFC-1918 CIDR, so we list the build-time
`VITE_SERVER_URL` host; (2) an `https://localhost` WebView blocks `http://` as Mixed Content →
`server.androidScheme: 'http'`; (3) cross-origin browser fetch to a no-CORS server is blocked by CORS →
`plugins.CapacitorHttp.enabled` routes the app's fetch through native networking (no CORS; cleartext
still gated by the NSC via OkHttp). All three documented in `reader/BUILDING.md` + capacitor.config.ts.

**Offline-shelf fix (persistence hardening).** The device kill/relaunch test exposed a pre-existing
R1a bug: `Shelf.load()` populated its list only from the server fetch (`if (!up) return`), so **offline
the shelf showed no owned books** despite its "showing owned books" label — you couldn't reopen a
downloaded book after a kill with no network. Added `shelf/checkout.ts#residentEntries` (enumerates
`books/{id}/manifest.local.json` + local `meta.json`, no network) and the shelf now lists resident books
when offline. Regression-tested (`shelf/residents.test.ts`).

**Decisions**
- **Capacitor 7.6.8** (not 8/9): works with the box's JDK 17; 8/9 would force a JDK 21 install.
  compile/target SDK kept at Capacitor's AGP-tested **35** (installed `platforms;android-35`) rather than
  retargeting to 36.
- **iOS added, deferred.** `npx cap add ios` laid down `ios/` on Linux (it skips `pod install` /
  `xcodebuild`); committed as-is per DESIGN §2 (Android-first, iOS unpolished). Building it needs macOS
  (steps in BUILDING.md).
- `android/` + `ios/` committed as standard Capacitor projects; build outputs, `.gradle/`, Pods, and the
  `cap sync`-generated web-asset copies are git-ignored (regenerated by `just android-build`).

**Emulator acceptance** (self-serve, CC — `system-images;android-36;google_apis;x86_64`, Pixel 6 AVD,
KVM): installed the APK (built `VITE_SERVER_URL=http://10.0.2.2:8720`); over the host loopback the shelf
**listed and checked out** the fixture bundle — all 18 reader-required files (incl. binary webp)
sha256-verified → **Resident** (proves CapacitorHttp binary transfer + `crypto.subtle` on
`http://localhost` + CapacitorStorage writes); **storage self-test PASS**; read page 1 (byte-faithful
text, plate from resident storage, Literata vendored font); cast interstitial with resident portrait;
hardware Back closed the cast overlay; Dark theme flipped the status-bar icons; **airplane mode ON** →
turned pages + searched ("wanderer" → 6 highlighted results from the persisted 18 KB index) with zero
network; **force-stop + relaunch (still offline)** → resident bundle, position (page 4), prefs (dark),
and search index all intact. `just android-build` produces the APK.

**Verification** — reader 146 vitest (was 143; +CapacitorStorage mocked contract, +residentEntries) + 5
Playwright (unchanged; native code guarded, safe-area env()=0 on desktop) · eslint + tsc clean (reader,
admin; `android`/`ios` ignored) · `build:check` still green (2 vendored woff2, no CDN) · server 290
passed / 5 deselected (untouched) · ruff clean · gen-types NO DRIFT. **Physical-device walk is
human-pending** (steps in BUILDING.md + the PR); it also covers most of M1's device box.

## R4 — Reader: search, dramatis personae, settings/typography (2026-07-14) — shipped

The reader's last three features before Android, all working with the API server dead. **Search:** a
MiniSearch index over `{id, seq, text}` (one doc per page), built at checkout completion
(`shelf/checkout.ts`, best-effort — a build error never fails a checkout) and persisted via `toJSON`
to `books/{bookId}/search-index.json`; already-Resident books and the fixture (which never checks out)
build on first search (`search#ensureIndex`). The `SearchPanel` slide-over queries as you type
(prefix + fuzzy 0.2), lists page hits with a `<mark>`-ed snippet, and jumps to the page + pulses it
(reusing the annotation flash-page). **Dramatis personae:** a full-screen overlay (NOT injected into
`pageIds` — positions/anchors stay byte-stable), gated by the ADR-0008 furthest-read filter
(`cast/filter.ts` — a character mentioned only ahead of furthest-read is hidden). Auto-shows once as an
interstitial before chapter 1 on a fresh book; reopens from a toolbar "Cast" button; portraits resolve
the resident `images/thumbs/portraits/{slug}.webp` derivative (monogram fallback). **Settings:** the
full screen replaces the R3 stub — typeface (Literata/Inter, both **vendored** as latin variable woff2
with their OFL licenses under `src/assets/fonts/`, zero external font loading), font size (5 steps),
theme (light/sepia/dark) via a small design-token layer in `index.css`; per-device prefs
(`settings/prefs.json`, never synced) applied at the App root by `usePrefs`. Reachable from a ⚙ button
in the reader bar (needed in fixture mode where there is no shelf header).

**Decisions**
- **Furthest-read for the cast filter is live** (`max(synced furthest, session max seq)`), so a
  character passed this session appears when the cast page reopens — not only after a sync.
- **Cast page auto-interstitial** shows only on a fresh open (no saved position). This changed
  fresh-boot UX, so the R3 sync acceptance's `boot()` now dismisses it (and targets the chapter title
  by role, since the wanderer's one-line "…winter quay" collided with the title text matcher).
- **Fixture left untouched.** The named ADR-0008 scenario (mentioned p40, furthest 30) can't live in a
  6-page fixture, and adding a hideable major would ripple into generated portrait assets + prompt
  fixtures + a full deterministic bundle regen. Instead the named test is a pure vitest
  (`cast/filter.test.ts`) plus a component test that renders the real overlay with a synthetic hideable
  character (`cast/CastPage.test.tsx`); the browser test verifies the overlay end-to-end on the real
  fixture.
- **Index stores page `text`** (in MiniSearch `storeFields`) so hits carry text for snippets with no
  second read. Novel-scale cost is the text roughly doubled in the persisted index — acceptable for v1.
- **Search-jump match-flash** reuses the whole-page `flash-page` pulse + `pendingRestoreChar` scroll,
  rather than a new per-run Page prop — lands on the match paragraph, no byte-faithful-render changes.

**Verification** — reader 145 vitest (was 130) + 5 Playwright (2 R3 sync + 3 R4: search/persist/flash,
cast auto-open + reopen, theme+font survive reload — all with `/api`+`/health` aborted to simulate the
server down). `npm run build:check` (`scripts/check-dist-fonts.mjs`): 2 vendored `.woff2` in `dist/`,
no `fonts.googleapis`/`cdn` references. server 290 passed / 5 deselected (fixture untouched). eslint +
tsc clean (reader, admin-ui) · ruff clean · gen-types NO DRIFT. Fixture index: 6 pages, built once on
first search (~ms), loads from disk on reload with no rebuild (asserted via the build counter).

## R3 — Reader: sync client + profile picker (2026-07-14) — shipped

Annotations and positions now flow to the S12 sync API and merge back — opportunistically,
reachability-guarded, and never on the reading path. First-run profile picker replaces R2's hardcoded
`DEV_USER_ID`; all local files re-namespace to the chosen profile. Server untouched; S12 is
authoritative — the client PUTs a full doc and adopts the server's merged answer whole (never
field-merges). The one piece of local merge logic is a bit-for-bit port of `sync/merge.py`, pinned to
it by a shared vector both suites run.

**Shipped**
- **`sync/merge.ts`** — TS port of `server/src/scriptorium/sync/merge.py`: annotations union-by-`id`,
  LWW by `modified` (ISO **string** compare, never `Date`), tombstones merge identically, output
  canonical (dedup + sort by `id`); positions `furthest` = tuple-max on `(page_seq, char)` ignoring
  time, `current` = LWW with `(page_seq, char, device)` tiebreak. Includes `canonicalJson()`
  reproducing Python `json.dumps(sort_keys=True, ensure_ascii=False)` (sorted keys, `", "`/`": "`
  separators, raw non-ASCII) — the equal-`modified` tiebreak that a naive `JSON.stringify` would break.
- **Shared anti-drift vector `shared/test-vectors/sync-merge.json`** consumed by **both**
  `reader/src/sync/merge.test.ts` and new `server/tests/test_sync_vectors.py` (both orders per case →
  commutativity). A non-ASCII equal-`modified` case genuinely pins `ensure_ascii=False`.
- **`sync/client.ts`** — `HttpSyncClient` mirroring `shelf/client.ts` (same-origin base, `/health`
  cached 60 s, `reachable(force)` to bust the cache for manual/reconnect): `fetchUsers`,
  `get/putAnnotations`, `get/putPositions` (404 → `null`).
- **`sync/engine.ts` + `sync/useSync.ts`** — `syncAllBooks` reachability-guards, canonicalizes the
  local annotation doc, PUTs, **adopts the merged doc by whole-file write**, stamps `sync-state.json`,
  and dispatches a `scriptorium:synced` window event so open surfaces refresh live; failures are
  **silent** (cloud-off indicator, local edits preserved). `useSync` wires the four §13 triggers —
  foreground (`visibilitychange`), reconnect (`online`), 10-min interval, manual — installed once per
  profile so **page-turns never fetch**. Book-close fires from `App` on a read→shelf transition.
- **`profiles/`** — `ProfilePicker` (avatar circles from `GET /api/users`, offline cache fallback),
  per-device `active-profile.json`, and `migrateDefaultTo` (one-time move of R2 `annotations/default/*`
  + un-namespaced `positions/*` under `{user}/`, idempotent + non-clobbering).
- **Namespacing** — `annotations/store.ts` + `readerview/position.ts` thread the active `user`
  (positions now `positions/{user}/{book}.json`); `App` gates the whole app (incl. fixture mode)
  behind the picker and prop-drills `user` + sync status.
- **UX** — `SyncStatusBadge` (cloud-off / "Synced N min ago", tap to sync) in the app header + reader
  bar; **jump-to-furthest chip** in `Reader` (Continue opens `current`; chip when `furthest > current`,
  refreshed live after sync); minimal **Settings** stub (profile switcher, Sync now, storage status).

**Verification** — reader **130 vitest** (was 93): shared merge vectors (24), engine (fake-server
adopt/silent-fail/positions/event), migration, picker. Server **290 passed / 5 deselected** (the new
shared-vector test included; no server change). Lint + tsc clean; no type drift (no schema change).
- **Two-context Playwright acceptance — VERIFIED** (`reader/e2e/sync.spec.ts`, `just reader-e2e`): two
  isolated contexts (= two devices), same profile `kris`, fixture book, edited **offline**
  (`setOffline`) — A highlights + reads to p5, B (later) notes + reads to p3 — then sync. Asserts the
  two annotation docs are **byte-equal** with both edits (read straight from OPFS), `furthest` = p5 on
  both, B's `current` = p3, and the **jump-chip visible on B**. Then delete-on-A / recolor-on-B (later)
  → later-modified wins identically on both (deletion lost, colour pink). Second test: with the server
  up, **zero `/api` requests during page-turns**. Fixture-mode reader + a Vite dev proxy to the live
  FastAPI (server has no CORS and is untouched this cycle). See NOTES "From R3".

## R2 — Reader: annotations (highlights, notes, bookmarks) (2026-07-14) — shipped

Highlights/notes/bookmarks with byte-solid anchors. The fiddliest client cycle: anchors are UTF-16
code-unit offsets into the immutable canonical page text (dumb integers, safe forever because published
text never changes), and the anchor round-trip gets the deepest test in the repo. All writes are already
R3-mergeable (wire shape, uuid ids, ISO `modified`, tombstones); sync/merge itself is R3. No schema
change, no server change.

**Shipped**
- **`annotations/anchors.ts`** — pure DOM↔offset mapping, reusing `readerview/pagetext.ts` verbatim (no
  forked math): `domRangeToAnchor(range, container, pageText)` and `anchorToDomRange(anchor, …)`. Intra-
  paragraph offsets come from a boundary-`Range.toString().length` (the DOM spec handles text-node and
  element boundaries uniformly, and walks all descendant text), so both directions survive a paragraph
  segmented into highlight `<span>`s. Collapsed/inverted ranges and endpoints outside `.page-para` →
  `null`; offsets clamped into their paragraph so a stale anchor never throws.
- **`annotations/segments.ts`** — pure `paintParagraph(paraText, paraStart, highlights)` → contiguous
  runs; overlap painting is **later-on-top** by array order; `runs.join("") === paraText` always (the
  byte-faithful invariant holds under highlights, verse `\n` included).
- **`annotations/store.ts`** — local persistence at **`annotations/{user}/{bookId}.json`** (outside
  `books/`, so shelf Remove keeps it; §14 `{user}/{book}` namespacing with a single `DEV_USER_ID`
  `"default"` until R3's picker). `createHighlight`/`createNote`/`updateAnnotation`/`deleteAnnotation`
  (tombstone: `deleted:true` + `modified` bump)/`toggleBookmark` (`{0,0}` page-level). `crypto.randomUUID`
  ids, ISO times via an injectable `now` (mirrors `position.ts`); whole-file writes.
- **UX** (`SelectionBar`/`NoteSheet`/`AnnotationsPanel` + `Reader.tsx` wiring): select → floating bar
  (4 colors, Note→sheet, Copy via `navigator.clipboard`); bookmark toggle in the toolbar; annotations
  panel (filter by type/color, tap→jump to page + flash); tap a highlight → recolor/note/delete popover.
  `Page.tsx` renders each paragraph through `paintParagraph` (colored run → `<span class="hl hl-{color}">`,
  bare text stays a raw node; R1b-identical DOM when nothing is highlighted).
- **Tap-zone ↔ selection fix** (R1b-flagged): the transparent `.tap-zone` `<button>`s stole drag-select
  near the edges — **removed entirely**. Edge-tap page-turn now derives from the touch handler via a pure
  `readerview/nav.ts#edgeTapAction` (clean tap in outer 12%, only while the selection is collapsed); all
  page-turns early-return during a live selection. Text under the edges is now selectable.

**Verification** — reader **93 vitest** (was 60): the anchor round-trip property test reconstructs
**597 random selections character-identically, 461 of them cross-paragraph** (seed `0x1a2b3c4d`), plus
named astral (surrogate-pair), verse-`\n`, collapsed-reject, outside-text-reject, and segmented-DOM
consistency cases; `segments`/`store`/`nav` units; component tests (bookmark persist/restore across
remount, highlight survives reload rendering over the same chars, live selection blocks page-turn).
Lint + tsc + build clean; fixture-mode build inlines the fixture. Server **279 passed / 5 deselected**
(untouched). No type drift (no schema change). See NOTES "From R2".

**Reload-survival acceptance — VERIFIED in a real browser** (headless Chromium via Playwright against
`VITE_FIXTURE_BUNDLE=1` dev): select text → highlight → the annotation is written to **real OPFS** at
`/annotations/default/usr-ce8f5ebd29d0.json`, and after a full tab reload the highlight **re-renders
over the same characters** ("quiet ha"). This is the one path jsdom couldn't cover (real OPFS + real
Selection/Range) — now closed, reproducibly.

**Follow-up fix (found during that run):** the floating selection bar rendered above the viewport for a
selection near the top of a page (its "above the selection" transform went off-screen). `SelectionBar`
now flips **below** the selection when there isn't clearance above (`sel-bar--below`), so it's always
reachable. Note: the app is blank in the VS Code Simple Browser (sandboxed webview) — use a real
external browser; that is not a code issue.

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
serves the cross-package fixture image via `/@fs` (200, `fs.allow` working).

**Offline acceptance — VERIFIED (2026-07-14, automated in a real browser).** Ran headless Chromium
(Playwright) against the real server (built reader + library API served same-origin from `:8720`, a
throwaway seeded library): Download → **Resident** (OPFS gains `books/usr-ce8f5ebd29d0/manifest.local.json`
+ the page bundle); Open → page 1 shows the chapter title + plate, progress `1/6`; paged to `6/6` (far
plate present, no chapter header); plate → lightbox → Esc; back to `3/6`; **reload → restored to `3/6`**;
then **killed the server** and page-turn (`4/6`) + plate lightbox still worked from OPFS. **16/16 checks
pass.** Decisive evidence: every `/api/library/**` request is tagged to the `download` phase — **zero on
the read path** (open/page/reload/offline). The one non-automatable bit (a human eyeballing it) is moot;
the network-idle + server-dead reads are proven. NB: the app is blank in the VS Code Simple Browser
(sandboxed webview) — use a real external browser.

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

---

## M1 — First Full Bake (The Time Machine, pg-35) — 2026-07-14 — proving run (NOT complete; B2/B3 human-pending)

First real end-to-end run on real hardware (G434, all services local: TTS :8712, imagegen :8189
fronting ComfyUI :8188, Ollama). **PG #35 in via the real Gutendex path → an illuminated,
immutable, schema-valid bundle out, `failed_units=0` throughout.** This is the milestone landing.
Not marking M1 complete — that's the product owner's call after B2 (blind plate read) and B3
(phone walk) close.

**Config:** engraving / classic / era "1890s England" / portraits on. `SCRIPTORIUM_DATA=~/scriptorium-data`,
`RUNNER_TICK_S=5` for the bake.

**A0 — imagegen stale deploy (S10b) confirmed + fixed.** The running imagegen (started 07-12,
pre-PR#13) returned **1024²** for a `{832,1216}` request — reproduced live. `sudo systemctl restart
imagegen-service` (Kris) picked up the on-disk fix (`cf0f0a6`, `setNodeSize`). Confirmed **832×1216**
from actual rendered plate PNGs at scale (folded the `test_render_live` check into the real render to
avoid GPU collision). S10b render box CLOSED.

**A0b — carried live boxes closed.** `test_cast_live` / `test_ledger_live` / `test_prompts_live`
(`-m gpu`) ran against real TTS: **3 passed (33:47)**. Cast majors sane; ledger location carries
(study→lab→drawing-room); salience climbs 0.45→0.95 into the model demonstration. S5/S6/S8 live boxes
CLOSED. T13 KV binding already applied on the Ollama unit (`OLLAMA_FLASH_ATTENTION=1`,
`OLLAMA_KV_CACHE_TYPE=q8_0`).

**A2 — real TTS fixtures (carried since S5).** `tools/capture_tts_fixtures.py` (after a warm-up;
see NOTES on its cold-model 503) overwrote the hand-written fixtures with genuine captures. All shapes
matched schema. **Design-assumption check:** the real first-6 pages are entirely the Victorian frame
(study→laboratory), not the far-future arc the hand-written fixtures invented — so `cast-canonicalize`
captured `time-traveller`+`filby` (Weena is far-future; `weena.json` retained as a spare). This exposed
**four latent test assertions coupled to exact LLM content** (specific aliases, which page holds
`scene_changed`, which page holds a warning) — a violation of "never assert exact LLM content" and of
the fixtures README's own "a re-capture stays green" promise. Per owner decision, relaxed all four to
schema/shape/cross-ref checks. Offline suite **290 passed**, ruff clean. Commit `ea8a7b5`.

**A3/A4 — the bake.** Gutendex ingest (P0 inline ~1s): 58 pages, **16 chapters (I–XVI)**, 0 warnings.
P1 mentions ~28 min, P2 cast ~3 min, P3 ledger ~36 min, P5 prompts ~11 min → rest at `prompts_draft`,
**`failed_units=0`**. 19 plates selected (classic: 15 chapter_open, 3 scene_boundary, 1 fill), 8 majors
canonicalized, cover + 8 portraits. **Ledger tracked the set pieces**: time jump 0010–0011 (0.98),
far-future beach 0052/0054 (0.98), Morlock woods fire 0044–0050 (0.92–0.95), model demo 0004; 17 scene
changes, location carries. (Survived an IDE crash mid-bake untouched — the server runs independently.)

**B1 (human).** Kris edited a prompt, **retired plate 0025**, approved.

**A5 — render → publish.** Auto-advanced on approval. §7.4 observed: TTS unloaded before SDXL,
`models_loaded:[]` post-render. Render ~91s for the batch, `failed_units=0`. **`tools/verify_bundle.py`
EXIT 0.** Bundle: 62 MB on disk, `total_bytes_reader` 5.48 MB, 58 pages, **18 plates** + cover + 8
portraits (native/web/thumb trios), plates 832×1216.
**HEADLINE FINDING:** the retired plate **0025 still shipped** into the published bundle (its prompt +
2.3 MB image trio) — P7 renders `prompts/*.json` (glob), not the selection, and retire never deletes the
prompt file; `verify_bundle` is blind to the orphan. Reader-invisible (reader renders from
`selection.json`), but a real defect — filed with fix locations (NOTES From M1). Not fixed (proving run).

**A6 — kill-test (resumability, only real-hardware test).** Second bake (pg-1065, The Raven, 2 pp).
`kill -9` both uvicorn PIDs mid-mentions with page 0001 persisted + 0002 in-flight. Restart → runner
resumed from disk: **0001 mtime unchanged (skipped, not re-run)**, 0002 re-ran, phase reached
`mentions_done`, `failed_units=[]`. **Lost 0 completed units** — invariant #6 / §7.3 holds live.

**A7 — ADR-0007 backup.** `server/deploy/backup-data.sh` (rsync, fstype-aware, refuses empty
src/unmounted dest) + `README.md`. Backed up `SCRIPTORIUM_DATA` → Phison USB `/run/media/kb/TV`
(536 files, 129 MB). **Restore proven**: manifest.json sha256-identical + a plate PNG `cmp`-identical.
Commit `2f1a65c`. Caveats (NOTES): `sync/` empty until readers connect; USB is same-host removable
(LAN/off-site restic is the follow-up).

**Done-state:** ruff clean (server); offline suite 290 passed; schemas/types unchanged. Commits
`ea8a7b5`, `2f1a65c`. Findings filed in NOTES From M1. **§16 checklist:** ingest/chapters ✓, P1–P5
`failed_units=0` ✓, review-gate edit+toggle+approve ✓, render + plate count + cover/portraits ✓,
publish + `verify_bundle` ✓, kill-test ≤1 unit ✓, ADR-0007 backup ✓; **device checkout/offline/merge
(B3) human-pending.** M1 not declared complete.

**B2 — blind plate read (done, 2026-07-14).** Spoiler half done analytically (CC knows the text): all
18 plates depict only content at/behind their page — **no spoilers; causality invariant held in real
pixels.** Character continuity: engraving **style is excellent and consistent** across the set, but the
Time Traveller is only clearly framed in **0004** (character-scale interior); 0017/0046/0051/0055 are
wide landscapes where he is a speck or not discernible. Result: **continuity indeterminate** — not
morphing, but the protagonist isn't rendered large enough to compare, because every P5 prompt defaults
to "wide shot of …". Headline B2 finding → key input to the reader/prompt spec: **P5 should control
shot type for person-centric beats instead of defaulting all plates to wide establishing shots**
(filed, NOTES From M1).

---

## M1 follow-up — control-room usability + Chronicle art styles (2026-07-14)

Surfaced while the owner used the admin "New Book" screen himself (not a numbered cycle; three
owner-requested fixes during M1 usage).

**1. Gutendex search fix.** The wizard's book search 502'd: `gutendex.com` now 301-redirects
`/books?…` → `/books/?…` and the proxy client didn't follow redirects. Fixed the canonical URL
(trailing slash) + `follow_redirects=True` in `review_api.py`; same URL fix in `ingest/gutenberg.py`.
Added a respx regression test that mocks the 301 (the old tests mocked a direct 200 and never
exercised the redirect). Live-verified: "Anna Karenina" → 5 results.

**2. Chronicle art styles — real LoRA look (ADR-0013).** Owner wanted "the same art styles the
Chronicle uses." Probed the live imagegen-service: 12 LoRA-backed presets, and `/generate` already
accepts an optional `style` field the client never sent (ADR-0011 was deliberately style-neutral).
Reversed that: added required `imagegen_style: string|null` to the styles schema (regen types),
added the 12 presets to `data/styles.json` (16 total; kept the original 4 as `null` → prompt-only,
protecting the published Time Machine on `engraving`), made `RealImagegenClient`/`FakeImagegen`
`txt2img` take `style` (forwarded only when set → prompt-only requests stay byte-identical; fake
folds style into its digest only when set → determinism fixtures unchanged), and threaded
`style["imagegen_style"]` through P7 `render_to_spec` and P8 regen. ADR-0013 records the reversal;
`test_styles_catalog.py` guards every `imagegen_style` against the known preset set (typo → silent
prompt-only). Live-verified: API serves 16 styles, 12 with LoRA.

**3. Plain-English New Book screen.** De-jargoned `NewBookWizard.tsx` for the non-technical owner:
Source→"Choose a book" (default now book-search, was paste), Metadata/era→"About the book" with
"Time & place", Style captions "keeps characters looking the same"/"may look different", Density→
"How many pictures" (Most/Balanced/Fewest, was Lavish/Classic/Sparse "plates"), Portraits→"Character
portraits", "Create book"→"Make this book"; dropped §-refs and "M1"/"swatch"/"Gutendex". Updated the
admin smoke test (selects paste mode, new button label).

**4. Runner starvation bug (found by owner usage, fixed).** The owner's new book sat at `ingested`
for minutes after Start. Root cause in `runner.tick()`: it advances the oldest runnable job and
`return`s once per tick, but a job resting in a **no-worker-phase** state (`prompts_draft`, awaiting
the human review gate — `phase_for` returns `None`) was still selected and consumed the tick doing
nothing, **starving every newer job behind it**. Here the A6 kill-test leftover `pg-1065` (parked at
review) blocked the owner's book indefinitely. Fix: in `tick()`, skip a job whose state has no
registered phase (and isn't `waiting_gpu`) so the worker moves on to the next runnable job. Added
`test_review_gated_job_does_not_starve_newer_jobs`. After the fix the owner's book advanced
ingested→mentions→cast→… on its own (`failed_units=0`).

**Done-state:** ruff clean; offline suite **300 passed**; eslint+tsc clean (reader + admin-ui);
`gen-types` deterministic (only the intended `styles.d.ts` field diff); schemas/types in sync.
Not yet committed (awaiting owner go-ahead). Parked as before: second-picture-per-scene.

---

## M1 follow-up — "Pictures per scene" (multiple illustrations per page) (2026-07-14)

Owner baked a short 3-"chapter" paste, chose "Maximum" pictures, got ONE. Two stacked causes:
(a) markdown chapter headings required a space after `#` (`#Chapter` was ignored → 1 page), and
(b) books under 8 pages hit a "tiny-work" shortcut that ignored the density preset and capped at
1–2 plates. Owner's fix request: make it a **number** — "pictures per scene" from 1..N, woven in
**evenly**. That refinement let us drop the riskiest design option (an AI/ledger change to discover
extra "beats"): even spacing = deterministic paragraph segmentation, no GPU/TTS dependency.

**Shipped (server + reader + admin, all additive/back-compat):**
- **Stage 0 — chapters count.** `ingest/markdown.py` heading regex `\s+`→`\s*` (new ingests only;
  paginator bytes untouched). Tests for `#Chapter` / mixed / single-title-collapse.
- **Stage 1 — short books honor scenes.** Removed the `TINY_WORK_THRESHOLD`/`_tiny_work` ≤2 collapse
  in `selection/engine.py`; the mark→min_gap→fill pipeline now runs at every size (floor: never zero
  plates). Density is meaningful for small books again.
- **Stage 2 — pictures per scene.** New `images_per_scene` (int ≥1, default 1) on `BakeBody` +
  `meta.schema.json` (optional) + the New Book wizard ("5 · Pictures per scene"). New shared
  `selection/segment.py` `even_segments`/`expand_choices`: split a selected page's paragraphs into N
  even groups, UTF-16 anchors matching the reader's `pagetext.ts`. **Compound plate identity**: base
  image keeps the bare `page_id`; extras are `{page_id}-N` with optional `plate_id`/`anchor`/
  `segment_index` in `selection.schema.json` (+ broadened `prompt.schema.json` id pattern). P4 emits
  the expanded plates; P5 derives each plate's prompt from **its own segment** (causality-safe);
  P7's `.isdigit()` page-plate check → regex `^[0-9]{4}(-[0-9]+)?$` (the one silent-bug risk) and
  `_mark_rendered` keys on effective plate id; `reselect` diff-keys on effective id and re-select
  expands `fresh` too; publish/regen carry through by filename stem. Reader groups plates by page and
  weaves extras **between paragraphs** at their anchor (never mid-paragraph → byte-faithful
  `.page-para` DOM and R2 anchors untouched); single-image bundles render identically. A scene holds
  at most one picture per paragraph (documented limit).

**Live proof:** a real 4-paragraph ingest with `images_per_scene=2` → plates `0001` + `0001-2`
(even anchor); =3 → three at even anchors. **Done-state:** server ruff clean + **312 pytest**;
reader **148** + admin-ui green (tsc/eslint/vitest); `gen-types` deterministic; schemas/types in
sync. Existing bundles (The Time Machine) unchanged. Not yet committed (awaiting owner go-ahead).
Owner must **re-bake** Detective Brown (immutable) to see the new behavior.

## M1 follow-up — Private picture "Sets", Phase 1: model + "Pictures" menu (2026-07-14)

Owner wants art **private per person** with **multiple "Sets" per book** (create in a new style
or re-roll; delete). Full design + phasing in the plan file; this is **Phase 1 of 4** — the
schemas, a read-only listing, and a visible switcher shell. No generation, no per-account image
storage yet (those are Phases 2–4). The **words stay locked**; only pictures become swappable.

- **Schemas + types.** New `shared/schemas/artset.schema.json` (one set: book_id, user_id,
  set_id `^(default|set-[0-9a-f]{12})$`, kind default/style/reroll, label, optional style_id/
  source_revision, status, created) and `artset-list.schema.json` (per-(user,book) list +
  `active_set_id` + set summaries; the synthetic `default` entry needs no timestamp). Added both to
  `schemas.SCHEMA_KINDS` (+ 4 valid/invalid fixtures for the parametrized `test_schemas`). Regen
  `shared/types` → only `artset.d.ts`/`artset-list.d.ts` + index (deterministic).
- **Server.** New `scriptorium/artsets/` module + `GET /api/artsets/{user}/{book}` returning the
  Default-only list, schema-validated, with the sync API's `{user}`/`{book}` traversal guards.
  Router wired in `app.py`.
- **Reader.** New `reader/src/artsets/`: `activeSet.ts` (per-(user,book) active-set persisted
  locally at `artsets-active/{user}/{book}.json`, default `"default"`, offline), `useActiveSet`
  hook, and a **"Pictures"** overlay `SetPicker` (lists sets, marks the active one "In use"),
  reachable from the reader toolbar. No network anywhere in the module (ESLint fence intact);
  `platesByPage`/page text untouched — Phase 1 switch is a no-op on the images by design.
- **Single port (owner request).** Built `reader/dist` + `admin-ui/dist` and restarted the server;
  everything now serves from **:8720** (`/` reader, `/admin` admin, `/api/*`). Stopped the two Vite
  dev servers (5173/5174) so there is exactly one URL. (Single-port serving is the existing S11
  design; the two ports were only the dev-preview servers.)

**Done-state:** server ruff clean + **326 pytest**; reader **154** + admin-ui green (tsc/eslint/
vitest); `gen-types` deterministic (only intended additions); schemas/types in sync. Live: the new
endpoint returns the Default set on :8720 and the reader's Pictures menu opens offline. Not yet
committed (awaiting owner go-ahead). ADR-0014 (private art sets) lands with Phase 2 generation.

## M1 follow-up — Private picture "Sets", Phase 2: server-side make / delete (2026-07-14)

**Phase 2 of 4** (see the plan): the server engine that generates a private picture set for an
already-published book — in a chosen style or a re-roll — through the single-worker runner, and
deletes one. No reader download/switch yet (Phases 3–4); no new schemas. ADR-0014 records the design.

- **Storage/config.** New `cfg.artsets_dir` → `artsets/{user}/{book}/{set_id}/`; a set holds `set.json`
  (schema `artset`), `manifest.json` (reuses the `manifest` schema), per-picture provenance, and its
  `images/…`. `set_id = set-<12 hex>` (resolver-safe).
- **State machine (`bake/job.py`).** New `SET_RENDERING` (a GPU state) + distinct terminal `SET_DONE`,
  wired **explicitly** in `_build_transitions` (kept off the book `_CHAIN`) with `→SET_DONE` / `→FAILED`
  / `→WAITING_GPU` edges — the mandatory failure/park edges the runner's handlers need. `SET_DONE` added
  to `TERMINAL_STATES` + the runner's skip.
- **Set render phase (`artsets/phase.py`).** `SetRender` (`set_rendering → set_done`, is_gpu) mirrors P7:
  a leading `__unload__` (TTS unload + imagegen health → `waiting_gpu`), one unit per non-retired page
  plate (from the book's resident `selection.json`) + `cover` + `portrait-{slug}` per major cast, a
  trailing `__finalize__` (manifest + flip `set.json` to `ready`). Reuses the render **pure functions**
  (`wrap_prompt`/`_asset_spec`/`render_to_spec`, P5 `assemble_cover`/`assemble_portrait`) with the set
  dir as the explicit root — **not** `render_plate` (which hard-codes `job.book_id`). Page prompts are
  the book's approved, style-neutral prompts; cover/portrait re-assembled in the set's style; seed folds
  `set_id` so a re-roll differs. Registered in `app.py` `BAKE_PIPELINE` (unique `from_state`).
- **Service + endpoints (`artsets/service.py` + `api.py`).** `POST /api/artsets/{user}/{book}`
  (`kind` style|reroll, style_id?, label?) validates the style, writes `set.json` (generating), enqueues
  a job id `{book}#{set_id}` (server-internal — `#` never in a URL segment). `DELETE …/{set_id}` refuses
  `default`, removes the job + subtree. `GET` upgraded to scan real sets + reconcile a stalled
  `generating` against its job. The **create action is the review-gate approval** (ADR-0014) — no bypass.

**Tests:** drive `Runner([SetRender(FakeImagegen())])` over a seeded published book → set dir gets a web
image per plate + cover + portrait, schema-valid manifest, `set.json` ready, style prefix in provenance;
re-roll seed differs; `unload` 503 parks `waiting_gpu` then resumes; state-machine edges; endpoints
create/list/delete + 400/404 guards. **Immutability proof:** `library/{book}` byte-identical across
create + render + delete; no `work/{book}`; the book's own job id untouched.

**Done-state:** server ruff clean + **336 pytest** (offline, FakeImagegen); reader/admin-ui unchanged &
green; `gen-types` deterministic (Phase 2 adds no schema). Not yet committed (awaiting owner go-ahead).
Not user-visible yet — the reader "make/switch a set" UX is Phases 3–4.

---

## M1 follow-up — Private picture "Sets", Phase 3: private offline download (2026-07-14)

**Phase 3 of 4** (see the plan): the plumbing that gets a private set's images onto a device — server
serving endpoints + a reader download module — sha256-verified, stored **outside** `books/{id}`. No new
schemas (the set manifest reuses `manifest`). Still not user-visible (no picker wiring — that's Phase 4).

- **Server serving (`artsets/api.py`).** Two read-only endpoints mirroring `library/api.py`:
  `GET /api/artsets/{user}/{book}/{set_id}/manifest` and `…/files/{path:path}`, with `ETag = sha256`
  (from the manifest), `If-None-Match` → 304, the `{file_path:path}` converter, and a `_set_dir` guard
  (pattern-validate segments → `.resolve()` + `is_relative_to(artsets_dir)` → require `manifest.json`).
  `default` never reaches here (`_SET_RE` excludes it) — Default art is served from the resident book
  bundle. Additive routes; the existing list/create/delete routes still match unambiguously.
- **Reader download (`reader/src/shelf/artsetCheckout.ts`).** A sibling of `checkout.ts`, in `shelf/`
  (the only place besides `sync/` the ESLint network fence allows `fetch`). Reuses `sha256Hex` and
  `resolveReaderFiles` verbatim; a `HttpArtsetClient` (base URL from `VITE_SERVER_URL`) fetches the set
  manifest + file bytes. `artsetCheckout` runs the checkout walk (skip-if-good, verify/retry ×3, write
  `manifest.local.json` **last** = Resident marker) into `artsets/{user}/{book}/{setId}/` — outside
  `books/{id}` so Remove-book and immutability are untouched. `setState` (resident/incomplete/available,
  no network) + `removeSet` (subtree-only prune) round out the surface, exported from `shelf/index.ts`.

**Tests:** server `test_artsets_serving.py` — manifest served (schema-valid), a file served with the
manifest sha256 ETag, `If-None-Match` → 304, traversal → 400/404, missing → 404, unknown/`default`/
malformed `set_id` → 400/404, `library/` never touched. Reader `artsetCheckout.test.ts` (`MemoryStorage`
+ fake client) — images land under the set path (never `books/`), verified, `manifest.local.json` last;
resume skips good files; a corrupt file retries ×3 then throws (stays incomplete); `removeSet` deletes
only its subtree.

**Done-state:** server ruff clean + **347 pytest**; reader eslint + tsc clean + **158 vitest** (network
fence intact); `gen-types` deterministic (Phase 3 adds no schema). Not user-visible yet — Phase 4 wires
the picker's create/switch/download/delete and the `BundleReader` image-source swap.

---

## M1 follow-up — Private picture "Sets", Phase 4: reader multi-set switching (2026-07-14)

**Phase 4 of 4 — the payoff.** In the reader's "Pictures" menu Kris can now **make** a new set (a chosen
art style, or "same style, fresh pictures"), watch it get made → downloaded → switched automatically,
**switch** any set (instant + offline once resident), and **delete** one — all private to his profile.
Entirely reader-side: **no server or schema changes** (Phases 1–3 built every endpoint; `/api/admin/styles`
already lists the catalog). First cycle where the whole feature is usable on screen.

- **Image-source swap (`readerview/SetImageBundleReader.ts`).** A `BundleReader` that delegates every
  `readJson` to the book bundle (a set never changes words/layout/anchors) but resolves `imageUrl` from the
  set's resident folder `artsets/{user}/{book}/{setId}/`. `Reader` holds an `effectiveReader` — the base
  book reader on Default, a `SetImageBundleReader` on a resident personal set — and passes it to
  `Page`/`CastPage`. Because `Plate`'s effect keys on the reader instance, swapping `effectiveReader`
  re-resolves every plate; `platesByPage`/`selection.json` are untouched. The set reader disposes only its
  own object URLs.
- **Control client (`shelf/artsetApi.ts`, `HttpArtsetApi`).** list/create/delete + `/api/admin/styles`
  catalog, in `shelf/` so the ESLint network fence stays green (reuses `ApiError`).
- **State machine (`artsets/useArtsets.ts`).** Owns the menu's data: the server list merged with each set's
  local residency; **create → poll (~2 s) until ready → auto-`artsetCheckout` → auto-switch**; delete
  (server + local subtree, reverting to Default if active); and an **offline fallback** — a locally-cached
  list filtered to Default + already-downloaded sets, make/delete disabled — so reading a resident set never
  needs the network. `SetPicker` upgraded to a per-row action (Use / Download & use / Making… / failed) +
  ＋ New set (style sheet) + Delete; new CSS.

**Tests (all reader-side, offline, behaviour/shape only):** `artsetApi` (URL/verb/parse/ApiError via a
stubbed fetch); `SetImageBundleReader` (JSON from book, images from set, null when absent, dispose scope);
`SetPicker`+`useArtsets` (make→generating→ready→auto-download→active; style vs re-roll body; delete reverts
to Default; offline note + disabled make); a `Reader` integration test proving a switch **changes the
plate's image `src`** from the book blob to the set blob. The create action stays the review-gate approval;
no new AI text.

**Done-state:** reader eslint + tsc clean + **172 vitest** (network fence intact); server ruff clean +
**347 pytest** (unchanged); `gen-types` deterministic (no schema). Reader **dist rebuilt** so the one-port
app on :8720 serves the new UI. The feature is now end-to-end usable in the reader.

---

## M1 fix — data-dir misconfig (500s + "books vanished") + /admin trailing-slash 404 (2026-07-14)

**Symptoms Kris saw:** creating a book → "Could not start the book: Internal Server Error"; the reader's
"Make books →" link → a "Not Found" page; and all previously-made books gone from the list.

**Root cause (one problem behind two of the three symptoms).** A prior server restart launched uvicorn
**without `SCRIPTORIUM_DATA`**, so `config.py` fell back to the packaged default `/var/lib/scriptorium`
([config.py:104]) — a path that doesn't exist and the `kb` user can't create. The server was therefore
reading an empty `library/` (books "vanished") and every write (`create book`, `save reading position`)
hit `PermissionError` on `mkdir` → HTTP 500 (server log: `sync/api.py:87 _atomic_write`). **No data was
lost** — the real library was intact at `/home/kb/scriptorium-data/` the whole time (6 books + jobs). Fix
= relaunch with `SCRIPTORIUM_DATA=/home/kb/scriptorium-data` (the documented M1 dir). Not a code bug; an
ops misconfiguration from the earlier restart.

**Second, independent bug — `/admin` 404.** The admin SPA is mounted at `/admin` and Starlette only serves
it under `/admin/`; a bare `/admin` (the reader's link, or a typed URL) 404s. Two-part fix: the reader link
now points at `/admin/` ([Shelf.tsx:92]), **and** a server route `GET /admin` → `307 /admin/` so a typed
address also works ([app.py], registered before the static mount so the explicit route wins).

**Hardening so this can't silently recur.** New `_check_data_dir` runs at startup: it tries to create the
data dir and, if it can't, logs one clear ERROR naming the path and `SCRIPTORIUM_DATA` — turning a stream
of confusing per-request 500s into one obvious boot-time line. The default is unchanged (correct for the
deployed i5 box, ADR-0007).

**Tests:** `test_app_static.py` — `/admin` → 307 `/admin/`; `_check_data_dir` creates a missing dir and
logs (not raises) on an unwritable one.

**Done-state:** server ruff clean + **355 pytest**; reader eslint + tsc clean + **172 vitest**; reader
**dist rebuilt**; server **relaunched on :8720 with the correct data dir** — health 200, all 6 books listed,
a smoke create returned 200 (then deleted), `GET /admin` → 307. Books restored, 500s gone, links fixed.

---

## M1 fix — optional auto-approve of the review gate (`AUTO_APPROVE`) + live GPU/service wiring (2026-07-14)

**Context.** Owner runs the whole system on one machine as the only user with a local (free, fast) GPU,
and asked to remove the review step ("it's pointless"). Also caught two live ops issues while a book
("The Sun Also Rises", pg-67138) was baking: it parked at `waiting_gpu`, and the text step was pegging the
CPU while the GPU sat idle.

**Ops fixes (no code).**
- The :8720 server had been relaunched **without `TTS_URL`/`IMAGEGEN_URL`**, so it couldn't see the local
  GPU services (text-transform on :8712, imagegen on :8189) and parked every GPU-bound job. Relaunched with
  both URLs → health `ok`, book un-parked and resumed `mentions_running`.
- The text model (ollama `qwen3.5:9b`) was running **98% on CPU** because ComfyUI was squatting on ~6.9 GB
  of the 12 GB card, leaving too little VRAM. Freed ComfyUI's memory (`POST /free`) + unloaded the model
  (`ollama stop`) so it reloaded **100% on GPU** (util 77–98%, ~195 W; CPU load on it fell ~660%→~90%). This
  is the single-GPU "one program at a time" tradeoff the design already handles on the render side
  (P7 unloads TTS before render) — noted as a future auto-hand-off improvement.

**Feature — `AUTO_APPROVE` (ADR-0015).** Opt-in env flag (default **false**). When on, the single runner
auto-approves a job resting at `prompts_draft`/`in_review` and lets it advance to render on the same tick.
Not a bypass: the approval logic was extracted to `bake/approve.py::approve_job` and is now the **one**
implementation both the human `POST …/approve` endpoint and the runner use — same missing-prompt guard
(a renderable plate without a prompt still refuses and leaves the job parked for a human). Default-off keeps
invariant #4 ("no plate rendered before approval") and every existing test byte-identical; the dev box opts
in via `AUTO_APPROVE=1`. Reversible by dropping the env var.

**Files.** `bake/approve.py` (new, shared logic); `bake/review_api.py` (endpoint delegates to it, identical
409/422/200 behavior); `config.py` (`auto_approve` field + `AUTO_APPROVE` env); `bake/runner.py` (tick
auto-approves when the flag is on); `docs/adr/0015-auto-approve.md`; `tests/test_auto_approve.py` (runner
wiring: on → advances past the gate + locks the shot list; default off → stays parked; missing prompt → still
refused on the auto path).

**Done-state.** server ruff clean + **358 pytest** (3 new); no reader/admin/schema changes (no type regen
needed); server **relaunched on :8720** with `SCRIPTORIUM_DATA` + `TTS_URL` + `IMAGEGEN_URL` + `AUTO_APPROVE=1`
— health `ok`, text on GPU, book resuming and set to flow straight through to render.

---

## M1 — automatic single-GPU hand-off + live bake visibility (CPU/GPU badge, auto-refresh, step status) (2026-07-14)

**Why.** On this single-GPU box the LLM (text) and SDXL/ComfyUI (images) can't both stay resident.
The system already unloads the LLM before rendering (P7), but nothing freed ComfyUI before the *text*
phases — so after a render, ComfyUI kept ~7 GB and the LLM spilled onto the CPU (pegged CPU, idle
GPU). It had to be cleared by hand and recurred. Owner also asked the bake page to self-refresh, show
where each long step is at, and indicate CPU-vs-GPU.

**Automatic GPU hand-off (server).** New best-effort `runner.free_imagegen_gpu(cfg)`: before a *text*
GPU phase runs, discover ComfyUI's URL from imagegen-service `/health` and POST its `/free` — the
mirror of P7's "unload TTS before render" (§7.4 / ADR-0009). Phases carry `gpu_kind` (default
`"text"`; `Render` and `SetRender` set `"image"`) so render phases, which need SDXL resident, are
never freed. Injectable on `Runner` (like `sleep`/`wake`/`gpu_gate`); with `IMAGEGEN_URL` unset it's
a no-op, so existing tests are unaffected. Verified live: after The Raven rendered, The Sun Also Rises
resumed the text phases with the LLM on the GPU (ComfyUI auto-released 6.9 GB → 316 MB) — no manual
step.

**Live GPU/CPU status (server).** New `scriptorium/gpu_probe.py` (best-effort `nvidia-smi` + `ollama
ps` parse; never raises) behind `GET /api/admin/gpu` → `{gpu:{present,util_percent,mem_*},
text_model:{loaded,name,processor}, summary:"gpu"|"cpu"|"idle"|"unknown"}`. Degrades to "unknown" on a
box without those tools (e.g. the i5).

**Bake page visibility (admin-ui `BookDetail`).** (1) Auto-refresh: polls the job every 3.5 s while
active (not at published/failed/paused) — no more clicking Refresh. (2) Per-step status: a plain
"⏳ Working on: <friendly phase>… (Xs on this step · refreshing automatically)" line, and the
milestone row now lights up the step being *worked toward* (so a `*_running` state shows ▸ on its
target milestone), plus a "✓ Done" line when published. (3) CPU/GPU badge next to the state: green
"⚡ GPU · N%", amber "⚠ CPU (slow)" for the spill, grey idle/unknown — polled from `/api/admin/gpu`,
best-effort (errors just clear it).

**Files.** server: `bake/runner.py` (free_imagegen_gpu + wiring), `bake/phases/p7_render.py` +
`artsets/phase.py` (`gpu_kind="image"`), `gpu_probe.py` (new), `bake/api.py` (`GET /gpu`),
`tests/test_runner.py` (+2 hand-off tests), `tests/test_gpu_probe.py` (new). admin-ui:
`api/types.ts` (`GpuStatus`), `api/client.ts` (`getGpuStatus`), `features/detail/BookDetail.tsx`
(effects + activity line + milestone + badge), `test/smoke.test.tsx` (`/gpu` mock).

**Done-state.** server ruff clean + **366 pytest** (+8); admin-ui eslint + tsc clean + vitest green;
no reader/schema changes (`shared/types` clean after regen); admin **dist rebuilt**; server
**relaunched** with `SCRIPTORIUM_DATA`+`TTS_URL`+`IMAGEGEN_URL`+`AUTO_APPROVE=1` — `/health` ok,
`/api/admin/gpu` live (`summary:"gpu"`), and the text phase running on the GPU via the automatic
hand-off (no manual intervention).

## M1 fix — illustrations spread evenly (ADR-0016: `images_per_scene` is a density dial, not a per-page multiplier) (2026-07-15)

**Symptom (Kris, on The Sun Also Rises).** With more than one picture per scene, all the pictures
piled up at the *start* of the scene (a few sentences apart), then a long run of text had none.

**Root cause.** The selection **engine** already spreads illustration pages evenly, but the
"pictures per scene" step (`selection/segment.py` `even_segments`/`expand_choices`) split **one
~550-word page** into N slices and hung **all N pictures on that single page**. A page is only a few
paragraphs, so they clustered at its top and the rest of the scene got nothing. The reader renders
faithfully — no reader change.

**Fix (density dial).** New pure `effective_params(params, images_per_scene)` in
`selection/engine.py` scales the effective preset tighter (`min_gap ← round(min/n)`,
`max_gap ← max(round(max/n), 2·min_gap)`), so a higher dial makes the engine's own even-spacing
mechanism select proportionally **more distinct pages**, one picture each, spread across the whole
book. `n == 1` returns the preset unchanged → **byte-identical** to a single-picture bake;
`max_gap ≥ 2·min_gap` (the fill-window invariant) is preserved. Applied at both selection call sites
— `p4_select.run_unit` and `review_api.do_reselect` — each now `expand_choices(..., 1)` (identity) and
writes the **effective** params into `selection.json`. The per-page split is retired for new work;
`segment.py` stays as the `n=1` identity path and to read already-published bundles' compound plates.
Engine stays text-free (spoiler invariant intact). Published bundles untouched (immutability).

**Copy.** Wizard step 5 "Pictures per scene" → **"How richly illustrated"** ("Higher = more pictures,
spaced evenly through the whole book"); `meta.schema.json` description updated (regen `shared/types`).

**Files.** server: `selection/engine.py` (+`effective_params`), `bake/phases/p4_select.py`,
`bake/review_api.py`, `tests/test_selection_engine.py` (+scaling/invariant/spread tests),
`tests/test_phases_p4.py` (rewrote the two per-page tests → even-spread + n=1 byte-identical),
`tests/test_reselect_api.py` (+parity test). shared: `schemas/meta.schema.json` + `types/meta.d.ts`.
admin-ui: `features/books/NewBookWizard.tsx`. docs: `scriptorium-DESIGN.md` §8, ADR-0016.

**Done-state.** server ruff clean + **387 pytest** (+6); admin-ui eslint + tsc clean + vitest green;
`shared/types` in sync after regen; admin **dist rebuilt**; server **relaunched** (`/health` ok).
Live proof (deployed package): dial 1 → 9 pictures (gaps up to 6 pages); dial 3 → 26 pictures every
1–2 pages, evenly spread, **no page carrying two** — no clustering, no empty tail.

## M1 fix — CPU/GPU badge samples a burst (no more false "stalled") (2026-07-15)

**Symptom (Kris, on A Tale of Two Cities in cast_running).** Badge showed "⚡ GPU · 2%" and the step
sat at 6m+, looking stalled. Live check proved it was fine: 295/295 mention pages done, cast.json
being written that second, GPU at 75–78%. The "2%" was `probe_gpu` reading `nvidia-smi` at a single
instant and catching an idle trough between LLM bursts.

**Fix.** `gpu_probe._sample_gpu` now samples nvidia-smi a short burst (5×, ~0.3s) and reports the
**peak** util (memory from that sample). Absent/unreadable cards degrade exactly as before (i5 →
"unknown"). New `test_util_reports_peak_across_a_burst`. server ruff clean + 388 pytest; server
relaunched (badge now reads the true ~78%, book advanced cast → ledger cleanly on resume).

## M1 fix — blank front-matter pages get nonsense pictures (ADR-0017: prune the table of contents) (2026-07-15)

**Symptom (Kris, on A Tale of Two Cities).** Pages showing a picture with **no story text**, and
**nonsensical pictures** (a floating book with golden threads = a literal drawing of the section
title "Book the Second — the Golden Thread").

**Root cause.** The book prints its own **table of contents**, and the H1 heading regex matches every
`CHAPTER <numeral> <title>` contents line → ~42 phantom **bodyless** chapters at the front → the
paginator emits one **blank page** per empty chapter (`word_count 0`) → P3 called `scene-update` on the
blank text → the model **hallucinated** a beat + salience → selection illustrated it. The real section
dividers (`Book the First--Recalled to Life`) use a *word* numeral, so the numbered heuristics missed
them and a divider got absorbed as a contents entry's fake body. NOT the density work (that's fine).

**Fix (two layers; selection engine untouched).** Ingest (`ingest/base.py`): `_section_headings`
detects short standalone `^(BOOK|PART|CANTO|VOLUME)` divider lines (bracketed by blanks) and merges
them with the numbered headings; `_prune_headings` then drops bodyless contents entries and **folds a
bodyless section divider into its section's first real chapter title** (a divider survives only if the
next chapter has a body — discards the contents-list copy, keeps the body one). Safety net
(`bake/phases/p3_ledger.py`): a page with empty/whitespace text is written a **neutral ledger**
(salience 0.0, empty beat) and the model call is **skipped** — any stray blank page can never be
selected or illustrated. On the real #98 text: **45 chapters** (was 90), **0 blank pages** (was 42),
~135.5k words preserved, "Book the First/Second/Third" kept as headings.

**Files.** server: `ingest/base.py`, `bake/phases/p3_ledger.py`,
`tests/fixtures/sources/pg_toc.txt` (new), `tests/test_ingest.py` (+TOC/divider test),
`tests/test_phases_ledger.py` (+empty-page neutral-ledger test). docs: `scriptorium-DESIGN.md` §5.1,
ADR-0017.

**Done-state.** server ruff clean + pytest green (+2). Verified end-to-end against the live Gutenberg
#98 text (ingest→paginate: 0 empty pages, 45 chapters, part titles preserved). Published #98 is frozen
(immutability) → **Kris will re-make the book himself** to pick up the fix; not re-baked here.

## M1 fix — Cycle 1: nested Part>Book>Chapter books ingest broken (ADR-0018: prose-based TOC-junk rule) (2026-08-08)

**Symptom.** Kris baked *The Brothers Karamazov* (Gutenberg #28054): unreadable. Real Chapter 1
didn't start until ~page 14, chapters scrambled/out of order (109 of them), and the first ~13 pages
were near-empty (word_count 1–6) — each just a `Book II. An Unfortunate Gathering` / `Epilogue` /
`Footnotes` line — every one drawing a nonsense picture. The characters page was blank (parked in the
junk before anyone is introduced). The ADR-0017 fix (flat *A Tale of Two Cities*) did **not** cover
this: re-ingesting #28054 with then-current code reproduced it.

**Root cause.** *Karamazov* nests Part>Book>Chapter with per-book numeral **reset** and a **dense**
(un-blank-bracketed) printed contents list. `_section_headings` needs a blank-line bracket, so the TOC
`Book …` lines were missed as dividers and **swallowed as a one-line "body"** of the preceding
contents entry; ADR-0017's `_prune_headings` kept any chapter with *any* paragraph, so those
near-empty entries survived as pages. `Epilogue`/`Footnotes` were outside the divider vocabulary.

**Fix (stay flat; ingest-primary + one safety net; selection untouched).** `ingest/base.py`: a
**prose-based junk rule** — a chapter is contents junk iff it has **zero non-heading prose**
(`_prose_word_count`/`_is_headingish`), replacing the "has any paragraph" gate (needs no magic
word-count; a one-sentence chapter still counts). `_H1` now matches `Book`/`Part`/`Canto` in Title
case (numeral stays UPPER-Roman/digit). `_prune_headings` **stacks** Part+Book labels into a section's
first real chapter (`"PART I — Book I. … — Chapter I."`). `_SECTION_WORD` (Epilogue/Prologue/Footnotes)
is **recognition-only**, deliberately NOT a boundary — making it one re-segments pg35 (*The Time
Machine* ends in an Epilogue) and drifts its byte-stable pagination golden. Safety net
(`bake/phases/p3_ledger.py`): neutral-ledger guard broadened from *fully empty* to **≤3 words**
(`_NEUTRAL_LEDGER_MAX_WORDS`), well below a real one-sentence page.

**On the real #28054:** 96 chapters (was 109 scrambled), real Chapter 1 leads (669 words), **0**
near-empty front pages (was ~13), Part/Book titles stacked as headings.

**Files.** server: `ingest/base.py`, `bake/phases/p3_ledger.py`,
`tests/fixtures/sources/pg_nested.txt` (new — dense TOC, two tiers, per-book reset, Epilogue/Footnotes),
`tests/test_ingest.py` (+nested test), `tests/test_phases_ledger.py` (near-empty neutral-ledger +
seed-text >3 words). docs: ADR-0018.

**Done-state.** server ruff clean + pytest green (391 passed, 5 deselected). pg35 pagination golden
unchanged (byte-stability held). Published #28054 is frozen (immutability) → **Kris will re-make the
book himself**; not re-baked here. Cycles 2 (picture captions) and 3 (character-face de-duplication)
follow as their own sessions.

## M1 — Cycle 2: picture captions in the reader (2026-08-08)

**Request.** Kris asked for a short line under each illustration telling the reader which moment of
the page the picture depicts.

**Approach (reader-only; no schema/bundle/pipeline change).** The depicted-moment text already
exists: each page's scene ledger carries `best_visual_beat`, a human-readable sentence derived from
that page's own text (spoiler-safe, ADR-0008), stored on `pages/*.json` and already shipped to the
offline reader. `Page.tsx` reads `page.ledger.best_visual_beat` (opaque provenance in the schema, so
read narrowly) and passes it as a `caption` to the **base (top) plate** only — one beat per page, so
extra segment-plates on a multi-image page render uncaptioned. `Plate.tsx` renders it as a
`<figcaption className="plate-caption">` inside the existing `<figure>`; `.plate-caption` styled muted
+ italic + centered in `index.css`. Because the beat is already in every published bundle, captions
appear on **already-baked** books too — no re-bake needed.

**Files.** reader: `readerview/Plate.tsx` (caption prop + figcaption), `readerview/Page.tsx` (read
beat, caption base plate; fixed the extras `.map` to not pass the array index as caption),
`index.css` (`.plate-caption`), `readerview/Reader.test.tsx` (+caption present-on-base /
absent-on-plateless test).

**Done-state.** reader eslint clean, tsc clean, vitest green (173 passed). Zero-online read path and
byte-stability untouched (no data written; caption is derived from existing page data at render time).

## M1 — Cycle 3: character faces — alias safety + junk filtering (ADR-0019) (2026-08-08)

**Symptom (Karamazov #28054).** One person → many faces (Dmitri = Dmitri Fyodorovitch = "Mitya"
became 3 characters/portraits; Alyosha appeared as an old general under "Alexey Fyodorovitch"), plus
junk cast entries ("me", "peasant", "old-woman", "another-female-figure").

**Root cause (in the pure reducer `bake/reduce_cast.py`).** Rule 2c (single-token subset) had no
defense against a shared patronymic token ("Fyodorovitch" ⊂ both brothers); the same-page
co-occurrence guard over-fired on given-name/full-name variants that appear together (splitting one
person); and the only junk filter was bare subject pronouns (omitting "me"), with `is_person` never
removing a group from `cast.json`.

**Fix (server-side, deterministic; a false MERGE is worse than a false split).**
- **A1 junk:** `_STOP_NAMES` extends the pre-grouping drop to all pronoun/indefinite whole-names
  (catches "me"); `_drop_junk_groups` (before the major flag) drops a group that is single-page AND
  all-lowercase-generic (capitalization is the signal — real names/roles are title-cased; "the
  Morlocks" and recurring lowercase roles survive).
- **A2 patronymic safety (merge-reducing only):** rule 2c never merges on a token shared by ≥2 full
  names.
- **A3 containment merge:** an unambiguous *proper* containment (subset token in exactly one longer
  full name, e.g. "Dmitri" ⊂ "Dmitri Fyodorovitch") merges even across the co-occurrence guard; a
  mere article variant ("guard"/"the guard") does NOT, so co-occurring distinct "Guards" stay apart.
  Flag `_CONTAINMENT_OVERRIDES_GUARD` for a per-book escape hatch. `mention_pages` union kept exact.

**Deferred to the external text-transform-service (separate repo — Kris's chosen follow-up).**
Nickname/diminutive linking ("Mitya"↔"Dmitri", substring-disjoint — needs `cast-mentions` to emit
the alias); a real character-vs-role signal; normalized depicted-vs-cast matching for the P5 warning.
No in-repo string rule can link substring-disjoint names.

**Files.** server: `bake/reduce_cast.py`, `tests/test_reduce_cast.py` (+7 tests: object/reflexive/
indefinite drop, lowercase-junk drop vs capitalized/recurring keep, shared-patronymic no-merge,
given-name merge across co-occurrence, junk-never-major). docs: ADR-0019, NOTES-FOR-NEXT-CYCLES.

**Done-state.** server ruff clean + pytest green (398 passed, 5 deselected). No schema change; cast
schema unaffected. Published #28054 frozen → owner re-makes to benefit.

## M1 — Cycle 4: bake progress indicators + stall detection (2026-08-08)

**Request.** During processing the admin screen showed only "Working on: … (Xm on this step)" — a
client timer that keeps counting whether the bake is working or wedged, so a stall (the 67-minute
"Finding the characters" case) looked identical to slow progress and Kris had to ask to have it
checked.

**Approach (additive; no schema/bundle change).** The runner writes one artifact per finished unit and
`save()`s after each (so `updated_at` is already a per-unit heartbeat), and per-phase done/total is a
cheap artifact count. Server: new `bake/progress.py` — `phase_progress(job,cfg)` returns
`{units_done,units_total}` from on-disk counts keyed by state (mentions/ledger vs #pages;
render vs #prompts; cast vs #majors; prompts vs selection plates+portraits+cover; `None` for
resting/CPU phases; pseudo-units excluded; done clamped to total). `status_extras` adds `server_now`,
`seconds_since_activity`, and `expecting_progress` (started AND not a resting/human-gate/parked
state). `GET /api/admin/books/{id}` (`bake/api.py`) merges these onto `job.to_dict()`. Admin UI
(`features/detail/BookDetail.tsx` + `api/types.ts` + `index.css`): a live "398 / 613" counter + a
`.progress-bar`, an "updated Ns ago" readout, and a "no progress for N — may be waiting on a GPU
service or stuck" warning banner (threshold 180s, generous so a single slow unit never trips it).

**Files.** server: `bake/progress.py` (new), `bake/api.py` (get_book enrichment),
`tests/test_bake_progress.py` (new — 15 tests). admin-ui: `features/detail/BookDetail.tsx`,
`api/types.ts`, `index.css`.

**Done-state.** server ruff clean + pytest green (413 passed, +15); admin-ui tsc + eslint clean,
smoke test green. Also: relaunched the :8720 server as a **systemd --user service**
(`scriptorium-server.service`) with SCRIPTORIUM_DATA + TTS_URL + IMAGEGEN_URL so it survives session
teardown and always runs the committed code — the root cause of the "re-made but still broken" report
was a long-lived uvicorn holding pre-fix code.

## M1 — Cycle 5: unattended "kick off → wake to a done book" + honest status (ADR-0020) (2026-08-08)

**Request.** Kris wants to load a book, set settings, kick it off, and wake up to a finished book —
without the Start click, the review-gate approval, or a status timer that ticks whether or not
anything is happening. (On "safety": agreed there is none — local single-user tool; the only real
cost of skipping approval is a wasted overnight render or a wrong image frozen into an immutable
book. The current gate can't surface either anyway — raw prompts, no context — so it's friction with
no payoff. Making it *useful* is deferred; see below.)

**Findings.** The pipeline has two human halts: **Start** (`ingested`, `started=False` — no auto
path existed) and **Approve** (the review gate — already automatable via the sanctioned, default-off
`AUTO_APPROVE`, ADR-0015). After approve, render + publish already run unattended.

**Fix.**
- Server: new opt-in `auto_start` flag (env `AUTO_START`, `config.py`, default false, mirrors
  `auto_approve`); `bake/api.py run_p0` sets `job.started=True` when on (still ingests+paginates
  first; closes the pre-P1 chapter-edit window — the documented tradeoff). ADR-0020. With
  `AUTO_START=1` **and** `AUTO_APPROVE=1`, a created book runs itself to `published`, no clicks.
- Status honesty: `progress.status_extras` now also returns `unattended` (= auto_start && auto_approve).
  Admin `BookDetail.tsx` drives the activity line off the server's `expecting_progress` instead of
  `isActive`: it only says "⏳ Working on… (timer · updated Ns ago)" when the runner is actually
  advancing; otherwise it shows an honest "⏸ Waiting to start / Waiting for your approval / Waiting…"
  and an "Unattended — starts and finishes on its own" note. No more ticking clock implying work.

**Deferred (Kris's ask, needs go-ahead — NOT built this cycle):** make the review gate *meaningful*
so an OPTIONAL approval is worth using — show the picture plan in plain language (per illustrated
page: the `best_visual_beat` caption, which characters appear, the page-text snippet) and/or render
a few sample plates before committing the full batch, instead of a wall of raw prompts.

**Ops.** Relaunched `scriptorium-server.service` (systemd --user) with `AUTO_START=1 AUTO_APPROVE=1`
(+ existing SCRIPTORIUM_DATA/TTS_URL/IMAGEGEN_URL) so the running box is fully unattended.

**Files.** server: `config.py`, `bake/api.py`, `bake/progress.py`, `tests/test_auto_start.py` (new),
`docs/adr/0020-auto-start.md` (new). admin-ui: `features/detail/BookDetail.tsx`, `api/types.ts`.

**Done-state.** server ruff clean + pytest green (416 passed, +3); admin-ui tsc + eslint clean, smoke
green. Both flags default off → default behavior byte-identical; the running box opts in.

---

## M1 · Cycle 6 — reader detects a re-made book (ADR-0021)

**Bug (the one that burned a day).** After the pipeline fixes, Kris deleted + re-made *The Brothers
Karamazov*. The **fixed 600-page bundle on disk was correct** (verified by reading files: page 1 =
real Chapter 1; `plates/0006.png` = the widow/Fyodor room scene matching its beat; `plates/0015.png`
= young Alyosha in a field matching its beat). But the **reader kept serving the OLD broken 613-page
bundle** — wrong first page, caption≠picture — because it never noticed the book had changed.

**Root cause.** (a) Server: `revision` is read only from `library/{id}/meta.json`, which delete
purges, so a delete + re-make restarts at `revision 1` — same `(book_id, revision)` as the old
bundle. (b) Reader: cache keyed on `book_id` alone; residency is a local existence check that never
reconciles with the server; the hash-based `delta()` reconciler existed but had **zero callers**.
Manifest had only per-file `sha256`, no cheap single value to compare, and `revision` collided.

**Fix.**
- Server: manifest gains **`content_fingerprint`** = SHA-256 of the sorted `path\0sha256` file list
  (`p8_publish._content_fingerprint`, emitted by `build_manifest`). Pure function of the files, so it
  differs on any content change even when `book_id`+`revision` collide. Schema + regenerated TS types.
- Reader: new `checkForUpdate()` (one manifest GET, compares the fingerprint) flags Resident books
  whose server content changed; the Shelf shows **"Update available"** and an **Update** button that
  runs the now-wired `delta()` (fetch only changed files by sha256, prune removed). All in `shelf/`
  → zero-online read path preserved (ESLint fence intact).

**Immediate recovery (no code).** Remove + Download the book in the reader forces a fresh checkout of
the corrected bundle — the stopgap Kris used while this shipped.

**Files.** shared: `schemas/manifest.schema.json`, regenerated `types/manifest.d.ts`. server:
`bake/phases/p8_publish.py`, `tests/test_publish.py`, fixtures `tests/fixtures/bundle/manifest.json`
+ `tests/fixtures/schemas/manifest.valid.json` (fingerprint added), `docs/adr/0021-bundle-content-fingerprint.md` (new).
reader: `shelf/checkout.ts` (+`checkForUpdate`, wired `delta`), `shelf/index.ts`, `shelf/Shelf.tsx`,
`index.css`, `shelf/checkout.test.ts` (+ same-revision regression) and 7 test helpers updated for the
new required field.

**Done-state.** server ruff clean + pytest green (418 passed, +2); reader tsc + eslint clean, vitest
175 passed; schemas↔types deterministic (only `content_fingerprint` added). No page bytes changed;
immutability + byte-stability + read-path invariants intact.

**Not built (still deferred, needs go-ahead).** The meaningful/optional review gate with **sample
renders** before committing all plates — tonight is evidence it's worth doing, but it is a separate
cycle and was not the cause of what Kris saw.

---

## M1 · Cycle 7 (Part A) — alias publish-filter kills wrong-character illustrations (ADR-0022)

**Bug.** Pictures showed the wrong person: Marfa (a woman) drawn as Grigory ("old man, grey beard,
reading Lives of the Saints"); Mitya (an adult) drawn as a boy. Root cause is upstream `cast-mentions`
emitting garbage inside a character's `aliases[]` — pronouns and *other characters' proper names* —
which `reduce_cast` republished into `cast.json` unfiltered, after which `present_cast` cross-linked
the wrong character into a scene and the illustration LLM bound the wrong appearance.

**Fix (in-repo, deterministic).** `reduce_cast._filter_published_aliases` drops an alias whose norm is
a pronoun/stop-word (now incl. archaic "thou/thee/thy/thine/ye" and possessive "his") or equals the
canonical name of a *different* group. Filters contamination only — never links (diminutives stay the
external service's job, ADR-0019). Verified on real pg-28054 mentions: "Mitya" no longer carries
"Nikolay Parfenovitch"/"Ivan"/"Alyosha"/pronouns; a Marfa-only page no longer pulls in Grigory.

**Files.** `server/src/scriptorium/bake/reduce_cast.py` (+`_filter_published_aliases`, `_STOP_NAMES`),
`server/tests/test_reduce_cast.py` (3 new: pronoun drop, cross-name drop, present_cast cross-link
gone), `docs/adr/0022-alias-publish-filter.md` (new).

**Done-state.** server ruff clean, pytest 421 (+3); no page bytes changed (work-tree step only).

**Still to come (Part B, text-transform-service, separate repo):** harden `illustration-prompt`
(one scene, ≤3 figures, clean positive prompt, descriptor↔character binding) and `cast-mentions`
alias hygiene at the source; then re-bake Karamazov and eyeball. Part C (sample-render review) still
deferred pending the re-bake.

---

## M1 · Cycle 8 (pipeline half) — character consistency via portrait reference (ADR-0023)

**Why.** Text prompts now name/describe characters correctly, but SDXL renders them inconsistently
(young-officer Mitya → old monk / woman across pages). Feed each character's canonical portrait
(`images/portraits/{slug}.png`, already rendered) back into their page plates as an IP-Adapter
image reference so the figure stays the same person.

**Shipped (scriptorium pipeline half):**
- `render/imagegen.py`: `txt2img` gains optional `references: list[bytes] | None` (base64-forwarded
  only when set; folded into `FakeImagegen` digest only when set → `references=None` byte-identical,
  all fixtures green).
- `p7_render.py`: `render_plate` computes the reference via `_portrait_reference` (page plates only;
  `derived.depicted` → cast name/alias → portrait PNG bytes if present; else none). `Render.units`
  now renders `portrait-*` **before** page plates (a page depends on its characters' portraits).
- Tests: `test_phases_p7.py` new case asserts a depicted major's portrait bytes are passed as a
  reference and the portrait renders first; `references=None` paths unchanged. ADR-0023.

**Not yet (service half, next):** imagegen-service `/generate` must accept `references` + an
IP-Adapter SDXL workflow; ComfyUI needs `ComfyUI_IPAdapter_plus` + models (installed on box, awaiting
a ComfyUI restart). Until deployed, scriptorium must NOT be restarted on this code against the old
service. Phase 2 (multi-character regional identity) deferred.

**Done-state (this half).** server ruff clean, pytest 422 (+1). Also this cycle (Phase 0): oil-painting
style negative gained anti-anachronism terms (modern money/clothing); text-transform-service T16
polish (case-insensitive bans + cast-canonicalize temp) shipped separately.

---

## M1 · Cycle 9 — unattended-bake resilience: a TTS 5xx retries, not kills the job (ADR-0024)

**Why.** The overnight character-consistency re-bake (Karamazov, 600 pages) died at **page 301**. The
text service returned a one-off `500` (LLM emitted a lone UTF-16 surrogate `\ud835` it couldn't UTF-8
encode). `TtsClient._map_error` mapped 500 → `PipelineBug` → whole job `FAILED`, discarding 300 pages
of work and the entire unattended run over a single stochastic hiccup. That defeats AUTO_START's whole
point (ADR-0020): load a book, go to bed, wake up to a finished one.

**Shipped:**
- `bake/tts_client.py`: 5xx (500/502/504…) now → `UnitFailed` — retried on the 3× ladder, and if
  genuinely persistent, recorded in `failed_units` while the bake continues. 503 still →
  `GpuUnavailable`; 4xx (400/401/404/413) still → `PipelineBug` (real client bugs halt loudly).
  One line: `if status in _UNIT_FAILED_STATUS or status >= 500`.
- `test_tts_client.py`: parametrized 500/502/504 → `UnitFailed`; 400/401/404/413 → `PipelineBug`
  (regression note references the pg-28054 page-301 death). ADR-0024.

**Root cause fixed upstream too:** text-transform-service **T17** scrubs lone surrogates from model
output so the 500 never happens; this cycle is the belt (survive a transient 5xx) to that suspenders.

**Done-state.** server ruff clean, pytest 425 (+3). No page bytes changed; only the exception a
non-2xx TTS status maps to.

---

## M1 · Cycle 10 — optional portrait-review gate (ADR-0025)

**Why.** Portraits seed every illustration (ADR-0023), but they rendered inside the post-approval pass
with no chance to look first — a wrong portrait silently seeded hundreds of pages. Kris wanted an
optional stop: render all portraits, pause, eyeball/edit/regenerate each until happy, then draw the
book from the approved portraits. Decisions (asked): edit lever = **both** prompt and description;
during the stop = **wait for me** (hard stop, overriding unattended AUTO_APPROVE for this one gate).

**Shipped (server).**
- New states `portraits_rendering` (GPU) + `portraits_review` (resting), spliced into `_CHAIN`
  between `approved` and `rendering` (transitions auto-derive). Per-book `bake_config.portrait_review`
  flag (`BakeBody`, default false).
- `p7_render.py`: the single render split into `PortraitRenderEnter` → `PortraitRender`
  (portrait-only) → `Render` (cover + pages), sharing a new `_ImagegenPhase` base. `unit_done` skips
  already-drawn portraits, so no double-render and full resumability.
- `runner.py`: at `portraits_review`, rest for a human iff the per-book flag is set, else auto-advance
  to `rendering` (same tick) — keyed on the flag, not global `auto_approve`.
- `review_api.py` (reuses machinery that already spoke `portrait-{slug}`): `edit_prompt`/`edit_cast`
  allowed at the gate; description edits re-derive the portrait prompt (`rederive_portrait_prompt`,
  respecting a manual prompt override); `regen_plate` allowed at the gate; `plate_image` serves
  `images/portraits/`; new `POST /approve-portraits` (`approve_portraits`). `progress.py`:
  `portraits_review` is not-expecting-progress; `portraits_rendering` gets a portrait-count bar.

**Shipped (admin-ui).** New-book wizard "pause to review portraits" sub-toggle; `PortraitReview`
screen (image + editable prompt + editable description + per-portrait regenerate + approve); new
`portraits` hash route + `App` dispatch; `BookDetail` state-gated "Review portraits" button and the
two new states in the progress chain; `approvePortraits` client fn; new `JobStateName`s +
`CreateBookBody.bake.portrait_review`.

**Invariants.** Toggle-off is byte-identical (only phase boundaries move; offline P0→P8 golden
bundles unchanged). Portrait regen overwrites the work-tree PNG pre-publish; no published bytes
mutate. Gate is after approval, before pages — adds a gate, never a bypass.

**Done-state.** server ruff clean, pytest **439** (+10, incl. new portrait-gate phase/endpoint tests);
admin-ui tsc + eslint clean, vite build OK. No schema change → `shared/types` untouched. ADR-0025.

---

## M1 · Cycle 11 — durable fast worker cycle (tick default 120→5) (2026-08-11)

**Why.** The runner sleeps `RUNNER_TICK_S` between steps, so every phase boundary costs at least one
tick of idle wait. We'd cut this 120→5s via an env override on the running server (Kris: "that was
easy!"), but the override lived only in the process — any restart snapped back to the 120s default, so
the speed-up wasn't durable. Kris asked to make the 5s cycle permanent.

**Shipped.** `config.py`: `RUNNER_TICK_S` fallback `120` → `5` (`load_config`). The env var still
overrides in either direction; this only changes the unset default. Nothing else in the pipeline
moves — purely the between-steps wait.

**Safety.** The only cost of a fast tick is that a job idle-waiting on a powered-off/unreachable GPU
re-probes GPU health each tick; that probe fails fast or self-limits to its 15s timeout, and
Wake-on-LAN is off by default (`GPU_WOL_ENABLED=False`), so no WoL spam. Single-user LAN box → no
separate "production" to keep conservative; lowering the shipped default is the robust way to make it
survive restarts. Tests set `runner_tick_s` directly (e.g. `=1` in `_pipeline_build.py`), so none
depend on the default.

**Done-state.** server ruff clean, pytest green (non-gpu). No schema change → `shared/types`
untouched.

---

## M1 · Cycle 12 — trustworthy "Pictures" status: live count + bar + retry (2026-08-11)

**Why.** Making a picture set (ADR-0014) showed the reader a static "Making your pictures…" forever —
no progress, no liveness. Kris hit it: his "Comic Book" set had actually finished (`ready`/`set_done`)
but the screen still read "Making your pictures…", so he couldn't tell working from done from dead.
Root cause: the server sends only a 3-word status (`generating`/`ready`/`failed`) with no count, even
though it renders pictures one-by-one and knows exactly how many are done.

**Shipped (server).** `artsets/phase.py`: new `set_render_progress(cfg, job) -> (done, total)` —
`total` from the book's stable `selection.json` + `cast.json` (page plates + cover + one portrait per
major), `done` = pictures whose files all exist (reuses `_asset_spec`, mirrors `SetRender.unit_done`).
Deliberately NOT the generic `phase_progress` SET_RENDERING branch, whose `count(prompts)` total
tracks done (a set writes prompts lazily as it renders). `artsets/service.py` `_summary` (already
loads the job to reconcile a stalled generating→failed) attaches `render_progress {done,total}` while
`SET_RENDERING`; best-effort try/except so status never 500s; ready/failed carry none.

**Shipped (schema + reader).** `artset-list.schema.json`: additive optional `render_progress` on the
set item (regen → `shared/types/artset-list.d.ts`; `SetRow` inherits it via its `Summary` spread).
`SetPicker.tsx`: generating row shows "Making your pictures… X of Y" + a `<progress>` bar (rides the
existing 2s poll), failed row gains a **Retry** button. `useArtsets.ts`: `retry(setId)` = delete +
re-create with the same style (reuses the pending→auto-download→switch flow; no new endpoint).
`Reader.tsx` wires `onRetry`. `index.css`: slim gen-bar + retry button.

**Invariants.** No bundle bytes / page text / prompts / seeds change; the set render is untouched.
Additive optional field on a non-bundle sync/list format. No new network in the reader — the
ESLint zero-online read-path boundary test stays green; progress rides the existing poll and degrades
to plain text offline.

**Done-state.** server ruff clean, pytest **444** (+3 artset-progress); reader tsc + eslint clean,
vitest **178** (+2 SetPicker); `just gen-types` → only `artset-list.d.ts` changed. ADR-0014 (no new
ADR — additive UX/observability).

---

## M1 · Cycle 13 — admin Books list groups picture-sets under their book (2026-08-11)

**Why.** The admin Books list (`GET /api/admin/books`) returns every job flat, including the per-set
render jobs (id `{book}#{set_id}`, states `set_rendering`/`set_done`). A book with 15 style sets showed
as 1 book row + 15 "(untitled)" rows — the book buried, the set rows meaningless. Kris wanted one row
per book, expandable to reveal its picture sets by style name.

**Shipped (admin-ui only — no server/schema/API change; the data was already on the wire).**
- `features/books/group.ts`: pure `groupBooks(jobs)` → `{bookId, book, sets}[]` (`isSetJob` = id has
  `#`; orphan sets → `book:null`; groups sorted newest-activity first). Unit-tested (`group.test.ts`).
- `features/books/BooksList.tsx`: fetches the style catalog via the existing `getStyles()` and builds a
  `style_id → name` map (client-side — no new endpoint); renders one parent row per book with a
  "▸ N picture sets" expander; expanded rows show each set by **style name** (+ " (re-roll)" for reroll
  kind) and a friendly badge (`set_rendering → "making pictures"`, `set_done → "ready"`). Fixes a
  latent React key collision (rows had keyed on the shared `book_id`; now `book:{id}` / `set.id`).
- `api/types.ts`: `set_rendering`/`set_done` added to `JobStateName`. `index.css`: `.set-subrow` +
  `.set-toggle`.

**Invariants.** Presentational admin change — no reader/read-path, no bundle/schema/immutability, no
pipeline logic; server output unchanged.

**Done-state.** admin-ui tsc + eslint clean, vitest **5** (+4 grouping), vite build OK. Verified
against live data (Ted's Camping Trip → 15 sets group correctly).

---

## M1 · Cycle 14 — Pause takes effect mid-phase, not just between phases (2026-08-11)

**Why.** Kris paused a running bake (Karamazov, mid "finding characters" over 600 pages) and it kept
going. Root cause: `runner.advance_job` runs a whole phase's units in one loop, saving the job's
in-memory (running) state after every unit — so an operator Pause written to disk by the API is
overwritten within a second. `tick()` only checks for PAUSED *between* phases, so a pause during a long
phase was effectively ignored until the phase finished (~30 min for Karamazov).

**Shipped.** `bake/runner.py`: in the per-unit loop, after running a unit and before saving, re-read
the persisted record (`jobmod.load`); if it's gone or its state no longer matches the state we're
advancing (i.e. the operator paused/deleted it mid-phase), **stop without saving** — leaving the pause
intact. The unit's artifact is already on disk, so `unit_done` skips it on resume. Pause now lands
within one unit instead of never. Happy path is byte-identical (persisted state matches → normal save).

**Test.** `tests/fake_phases.py` `PausingPhase` (loads a separate Job and transitions it to PAUSED
while a unit runs — models an API pause mid-phase); `tests/test_runner.py`
`test_pause_mid_phase_is_honored_not_overwritten` asserts the job stays PAUSED with
`prev_state` set for Resume, and units after the pause never run.

**Invariants.** Resumability preserved (still persists after every unit on the happy path; artifacts
untouched). No change to GPU parking / review gate / transition table.

**Done-state.** server ruff clean, pytest **445** (+1). No schema/type/reader/admin change.

**Ops note (this incident).** The already-clobbered pause on pg-28054 was made durable out-of-band
(stopped worker → set `state=paused, prev_state=mentions_running` in its job record → relaunched) so
Ted's-Camping-Trip-v2 could take the worker. Root trigger of the wider outage was an unattended NVIDIA
driver upgrade (595.71.05→595.84) needing a reboot; picture-set renders resumed cleanly afterward.

---

## M1 · Cycle 15 — documentation, onboarding & repo polish (2026-08-11)

**Shipped.** First end-user-facing documentation set (previously the repo had developer/architect docs
only). Nothing in `server/`, `reader/`, `admin-ui/`, or `shared/` app code changed — docs, shell
scripts, and repo metadata only.

- **Banner + badges:** hand-authored self-contained SVGs — `docs/assets/banner.svg` (illuminated
  initial-capital wordmark) and `docs/assets/badges.svg` (local status pills, no shields.io dependency,
  keeping with the no-cloud ethos).
- **Rewritten `README.md`:** human-first — banner, plain-language pitch, a "two ways in" fork
  (read books / run a bakery), highlights, a Mermaid how-it-works diagram, screenshot gallery
  (placeholders), companion-project links (text-transform-service + imagegen-service, both public repos),
  trimmed layout table, brief dev quickstart.
- **Three guides under `docs/guide/`:** `reading-books.md` (warm, jargon-free reader onboarding — browser
  first, phone app second), `making-books.md` (the "load a book, go to bed, wake to a finished book" bake
  walkthrough), `self-hosting.md` (full operator setup: per-OS server + the GPU box, an env-var table, and
  unattended `AUTO_START`/`AUTO_APPROVE` mode).
- **One-command onboarding:** `scripts/setup.{sh,ps1}` (check tools → `uv sync` → build reader+admin dist)
  and `scripts/start.{sh,ps1}` (launch uvicorn on :8720; default `SCRIPTORIUM_DATA` to a stable
  repo-local `./scriptorium-data` so books never vanish — honors the data-dir rule). Complements the
  justfile dev flow; no Docker.
- **Screenshot tracking:** `docs/SCREENSHOTS.md` (authoritative capture list, 15 screens + hero) with a
  reusable `docs/assets/screenshots/_placeholder.svg` referenced everywhere until real shots land.
- **Per-package READMEs:** `server/`, `reader/`, `admin-ui/`, `shared/` — one screen each, linking back
  to the guides.
- **Repo metadata:** GitHub description + topics set; annotated tag `v0.1.0`.

**Decisions (confirmed with Kris).** Docs + start scripts (no Docker); hand-crafted SVG banner now (not a
placeholder); full self-host guide including the GPU box; both companion services linked to their public
GitHub repos.

**Verification.** All three banner/placeholder SVGs parse as valid XML; every relative markdown link
across the new docs resolves; `bash -n` clean on both `.sh` scripts; live boot test — `start.sh` on an
alt port served `/health` (JSON), reader at `/`, and admin `200` at `/admin/`. `.ps1` scripts verified by
review only (Windows path noted as less-tested in the guide). No app code touched, so `lint-all`/tests
are unaffected.

**Open-sourced.** `LICENSE` added — **MIT**, © 2026 Kris Bennett (Kris's call: "anybody can take it and do
anything with it"). README's license section rewritten accordingly and a `license MIT` pill added to the
badge strip.

**Out of scope (noted).** Real screenshots (placeholders only — next pass); Docker/Play-Store/
desktop-installer packaging; the still-missing developer `system-overview.md`.

## M1 · Cycle 16 — illustration quality: primary-only reference, period anchor, composition (2026-08-12)

**Why.** Kris reviewed the published *Brothers Karamazov* (458 plates, oil-painting) and found plates
that contradict their own caption — *"The woman kneels before Elder Zossima…"* drawn as two East Asian
Buddhist-looking monks with no woman; *"Pyotr Ilyitch sits while Madame Hohlakov shrieks…"* drawn as two
young women with no Pyotr — and asked whether this is simply the ceiling of a local model. It is not.
Measured over all 458 plates: **39% asked for 3–4 figures**, 78% for 2+, only 3.5% single-figure;
`derived.shot` reached the prompt on **2/458**; the configured era reached it on **32/458**; 198 plates
carried a "depicted not in cast" warning; **10 plates were anchored on a non-primary character**.

**Root cause (a bug, not a limit).** `_portrait_reference` violated its own ADR. ADR-0023 specifies
"primary character only", but the code looped over `derived.depicted` and took *the first label that
happened to resolve and have a portrait on disk*. When the real subject was a minor (no portrait) or the
transform over-qualified their name, a **secondary** character's face silently became the whole plate's
identity anchor. Plate 0033 fell through Nastasya (a minor) to the elder's monk portrait; plate 0345 fell
through the invented "Pyotr Ilyitch Karamazov" to Madame Hohlakov. Both symptoms are exactly "the anchor
character duplicated, the real subject missing".

**Shipped** (see [ADR-0026](docs/adr/0026-primary-only-reference-and-prompt-anchoring.md)):
- **Primary-only reference.** `portrait_reference()` resolves `depicted[0]` and nothing else; no match or
  no portrait → prompt-only render. Never borrow another character's face.
- **Real label resolution.** `build_cast_index` / `resolve_character`: exact fold → article/honorific
  strip ("The Elder", "Madame Hohlakov", "Father Zossima") → token-subset, most-specific-wins
  ("Pyotr Ilyitch Karamazov" → `pyotr-ilyitch`). An alias claimed by two characters is **ambiguous and
  resolves to nothing** — guessing a face is worse than none.
- **Provenance.** `render.reference_slug` added to `prompt.schema.json` (+ regenerated types), so a
  mis-anchored plate is findable without eyeballing the art.
- **Period anchor.** `wrap_prompt` gained `era` and emits `prefix + [era, ] + subject + [, shot] + suffix`.
  Previously `era` reached only the text transforms, so "monk in a red coarse coat" had no cue that it
  was Russian Orthodox.
- **Composition.** `derived.shot` finally used (close/medium/wide → framing language), closing the M1
  retro finding that person-centric beats render as landscapes with a speck — which is plausibly *why*
  ADR-0023's conditioning never visibly helped.
- **Global negative.** SDXL's stock failure modes (`duplicate, cloned face, two heads, extra limbs,
  bad anatomy, crowd, extra people`, …) now apply to all 16 styles, with anti-anachronism terms promoted
  out of `oil-painting`'s ad-hoc negative. Terms are de-duplicated; the subject's trailing full stop is
  dropped so the suffix no longer reads `"…her father., canvas texture"`.
- **References on every path.** Picture sets render **portraits first** and condition page plates on
  *that set's own* portraits (a set was previously rendered entirely prompt-only);
  `regen_published_plate` re-conditions instead of silently dropping the anchor.

**Decisions (confirmed with Kris).** Fix in-repo *and* in `text-transform-service` (see that repo's T19);
verify by baking a new picture set on the published book; resolve epithets/variant names to cast entries.

**Verification.** `ruff` clean; `uv run pytest -q` → **459 passed, 5 deselected** with no GPU services
running (was 444; +15 new). eslint + tsc clean on reader and admin-ui; `gen-types.mjs` idempotent. New
tests are strings-and-choices only, never image content: the two bad plates are pinned as regressions
(minor primary and unresolvable primary must **not** fall through to a secondary), plus era/shot/negative
composition and the first end-to-end assertion that `references` actually reach `txt2img` on the art-set
path.

**Immutability.** No published bytes change. Prompt strings differ for *new* renders only; new art lands
in `artsets/…` or as an additive `-rN`. The paginator and its byte-stability golden are untouched.

**Out of scope (flagged).** Corrupt cast merges — the `elder` entry has swallowed `Father Ferapont`,
`Zossima` and `Nastya` as aliases, and there are near-duplicate `Pyotr Ilyitch` entries; ADR-0022's filter
was meant to catch this and didn't (separate root cause in `reduce_cast.py`; the new ambiguity rule limits
the blast radius). Caption accuracy — the reader caption is `ledger.best_visual_beat` from P3, a different
string from the image prompt, and carries its own factual errors ("Dmitri must have killed *her* father").
Hand-edited descriptions leaking into art (`madame-hohlakov.visual_description` is currently
`"a dumb bitch who keeps talking"`, baked verbatim into her portrait). steps/cfg/sampler control — the
imagegen service exposes none (ADR-0011).

## M1 · Cycle 17 — cast alias de-contamination (2026-08-12)

**Why.** Cycle 16 made the portrait reference resolve from `depicted[0]` only and refuse ambiguous
labels — which immediately exposed how contaminated the cast data is. The published Karamazov carries
**731 aliases across 239 characters**; `"the old man"` is claimed by **nine** different characters,
`"Dmitri Fyodorovitch"` by six, and the group `elder` claims `"Zossima"` while a separate group is
named `"Father Zossima"`. ADR-0022's filter caught none of it: it only drops pronouns and aliases
equal to another group's *verbatim* canonical name. Kris called it before any re-bake — right call,
since contaminated aliases feed `present_cast` and put the wrong appearance in the prompt.

**Shipped** (see [ADR-0027](docs/adr/0027-alias-contamination-rules.md)):
- `_filter_published_aliases` gained three rules — **shared** (claimed by 2+ groups → dropped from
  all; it identifies nobody), **same name modulo title** (compare on title/article-stripped form, so
  `"Zossima"` collides with `"Father Zossima"`), and **not a name** (no capitalised token → a role or
  relational epithet: `"the boy"`, `"brother"`, `"mamma"`, `"his friend"`).
- New `scriptorium/names.py` holds the label folding now shared by cast reduction and render-time
  matching. They must agree about `"Father Zossima"` ≡ `"Zossima"` — disagreeing is how a plate gets
  anchored on the wrong face — so `p7_render` folds through the same module.

**Verification.** `ruff` clean; **462 passed, 5 deselected** with no GPU services (+3 new, one per
rule). Replayed against the real book: **731 → 199 aliases (73% dropped)**, with genuine variants
(`Kalganov`, `Fyodor Pavlovitch Karamazov`, `Ilyitch`, `Mr. Kalganov`) surviving.

**Deliberate costs, both recorded in the ADR.** The capitalisation rule assumes a capitalising script
(a lower-case-typeset book would lose aliases but keep every canonical `name`) — Kris's call, as the
cheapest large win. And when one character is wrongly split in two, a shared alias is now dropped from
both halves (`"Perhotin"` off `pyotr-ilyitch` and `pyotr-ilyitch-perhotin`); the *split* is the real
defect and merging it needs world knowledge, which stays upstream per ADR-0019.

**Not fixable here.** `fyodor-pavlovitch` still carries `"Kalganov"` and `"Smurov"` — other people
entirely. Nothing downstream can know that; fixed at source in text-transform-service **T20**.

**Applies to the next bake only.** `cast.json` is written at bake time, so a published book benefits
only from a re-bake — which is why Karamazov is being re-baked rather than given a picture set.
