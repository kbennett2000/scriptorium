# Scriptorium — Build Plan

**Status:** Approved — 2026-07-13
**Executor:** Claude Code (Sonnet). One cycle per dispatch. Before every cycle read `system-overview.md`, `scriptorium-DESIGN.md` (the sections the cycle names), and this plan's §0.

## 0. Cycle discipline

Identical to text-transform-service BUILD-PLAN §0, restated as binding here: plan mode first; scope is a fence (`NOTES-FOR-NEXT-CYCLES.md` for discoveries); ADR-first where a cycle says so (seeds in DESIGN §15 — transcribe, don't re-argue); tests land with code; definition of done = ruff clean (server) / eslint+tsc clean (reader, admin-ui) / non-gpu tests green / acceptance checklist done / `CYCLE-LOG.md` entry. Never assert exact LLM or image output content. Commits prefixed `S{n}:`/`R{n}:`.

**Fixture rule (critical for this repo):** every phase that calls a GPU service is developed and tested against **recorded fixtures** — captured JSON responses stored in `server/tests/fixtures/tts/` (produced once on the 5070 via a small capture script in `tools/`, or hand-written to schema where noted). Tests must pass on a GPU-less machine. Live-service tests are `-m gpu` and run only at integration checkpoints.

## 0.1 Prerequisites (human, once)

- i5: `uv`, Node 20+, `wakeonlan` package installed; `SCRIPTORIUM_DATA` dir created and owned by the service user; env: `TTS_URL=http://<5070>:8712`, `IMAGEGEN_URL=http://<5070>:<port>`, `GPU_MAC=<5070 mac>`, `GPU_WOL_ENABLED=true`.
- text-transform-service through **T3** deployed on the 5070 before S5 goes live (fixtures unblock everything earlier); through **T6** before the M1 bake.
- `imagegen-service` repo readable at S10 (the cycle reads its API from source).

## 0.2 Cycle index & dependency graph

| Cycle | Title | Needs | Size |
|---|---|---|---|
| S1 | Monorepo scaffold, schemas, ADRs | — | M |
| S2 | Ingestion adapters (txt/gutenberg, md, upload) | S1 | M |
| S3 | Paginator + golden tests | S2 | M |
| S4 | Job runner + state machine (fake phases) | S1 | M |
| S5 | P1+P2: mentions, reducer, canonicalize | S3,S4 (+TTS fixtures) | M |
| S6 | P3: sequential ledger phase | S5 | S |
| S7 | P4: selection engine | S6 (schemas only) | S |
| S8 | P5: prompt derivation | S7 | S |
| S9 | Admin UI v0 (wizard, book detail, review gate) | S4–S8 APIs | L |
| S10 | P7+P8: render + publish + verify_bundle | S8 (+imagegen repo) | M |
| S11 | Library + checkout API | S10 | S |
| S12 | Sync API (annotations, positions, backups) | S1 schemas | M |
| R1 | Reader: shell, shelf, checkout, reading surface, plates | S3 (fixture bundle) — live needs S11 | L |
| R2 | Reader: annotations (anchors!) | R1 | M |
| R3 | Reader: sync client + profile picker | R2, S12 | M |
| R4 | Reader: search, cast page, settings/typography | R1 | M |
| R5 | Capacitor Android + persistence hardening | R1–R4 | M |
| M1 | First Full Bake milestone | all except T8 | — |

```
S1 ─┬─ S2 ─ S3 ─┬────────────────────────┬─ R1 ─ R2 ─ R3 ─ R5
    ├─ S4 ──────┴ S5 ─ S6 ─ S7 ─ S8 ─ S9 │        R4 ──┘
    └─ S12 ────────────────────┐   S10 ─ S11 ─────┘
                               └────────── R3
TTS: T5/T6 fixtures feed S5/S6/S8; live TTS needed only for gpu-marked runs + M1.
```
S12 can be dispatched any time after S1 (it touches only schemas + files). R1 may start after S3 using `tools/make_fixture_bundle.py` (built in S3) so client work overlaps server work.

---

## Cycle S1 — Monorepo scaffold, schemas, ADRs

**Goal:** repo skeleton; every file format nailed down in JSON Schema before any code consumes it.

**In scope**
- Layout per DESIGN §3 (empty packages with `__init__.py` / placeholder `index.ts`); server `uv` project (deps: `fastapi uvicorn[standard] httpx pydantic>=2 jsonschema jinja2 pillow`; dev: `pytest pytest-asyncio ruff respx`); reader + admin-ui Vite React TS scaffolds (deps minimal now; reader adds `minisearch` here since ADR-0006 names it); root `justfile` (`server-dev`, `server-test`, `reader-dev`, `admin-dev`, `lint-all`, `test-all`).
- `shared/schemas/`: **meta, structure, page, cast, selection, prompt, manifest, annotations, positions, users, styles** — every field from DESIGN §4/§4.5/§9, with `description` strings (they're documentation). `bundle_version: 1`.
- TS type generation: `json-schema-to-typescript` wired into reader+admin builds (`shared/gen-types.mjs`), output `shared/types/*.d.ts` committed.
- Server: `config.py` (env per DESIGN: `SCRIPTORIUM_DATA`, `SCRIPTORIUM_PORT=8720`, `TTS_URL`, `IMAGEGEN_URL`, `GPU_MAC`, `GPU_WOL_ENABLED`, `RUNNER_TICK_S=120`); `GET /health` per §11.1 (TTS/imagegen pinged with 2s timeouts, degraded-not-error).
- ADRs 0001–0010 transcribed from DESIGN §15; `docs/adr/0000-template.md`; `CYCLE-LOG.md`, `NOTES-FOR-NEXT-CYCLES.md` seeded.
- `data/styles.json` seed with the four §9 styles (full strings from DESIGN).
- Python-side schema validation helper `scriptorium/schemas.py`: `validate(kind, obj)` loading from `shared/schemas` (used by every later cycle + tests).

**Acceptance**
- [ ] `just test-all` + `just lint-all` green on a fresh clone.
- [ ] A deliberately-invalid sample of each schema kind fails `validate()` in a parametrized test; a valid sample passes (write minimal valid samples into `server/tests/fixtures/schemas/`).
- [ ] `/health` returns degraded (not 500) with both GPU services down.
- [ ] TS types regenerate deterministically (`git diff --exit-code` after re-run).

---

## Cycle S2 — Ingestion adapters

**Goal:** DESIGN §5 exactly: `RawBook` from Gutenberg text, markdown, and direct upload/paste.

**In scope**
- `ingest/base.py` (`SourceSpec`, `RawBook`, adapter registry); `ingest/gutenberg.py` (Gutendex search + fetch + PG boilerplate strip + chapter heuristics 1–3 + warnings), `ingest/markdown.py` (§5.2 incl. front-matter), `ingest/textfile.py` (raw txt through the same heuristics, `source.kind: "user"`).
- Raw source archival to `work/{id}/source/`.
- Book-id derivation (§4.1) incl. `usr-` hashing.
- Fixtures: full Time Machine PG #35 text committed at `server/tests/fixtures/sources/pg35.txt` (public domain; grab once, commit); a synthetic md book with front-matter; a headerless txt (heuristics-fail case); a txt with ALL-CAPS chapter lines (heuristic 3 case).
- Tests: boilerplate strip (marker variants incl. missing markers → warning); each heuristic wins on its fixture; pg35 yields ≥10 chapters with plausible titles (assert count range + first title, not full list); md front-matter honored; id stability (same text ⇒ same `usr-` id).
- Gutendex HTTP calls respx-mocked in tests; one `-m network` live test (skipped by default).

**Acceptance**
- [ ] All above tests green offline.
- [ ] `python -m scriptorium.ingest --file fixtures/sources/pg35.txt --kind text` (small CLI shim for dev) prints chapter count/titles for eyeball; paste output into CYCLE-LOG.

---

## Cycle S3 — Paginator + golden tests + fixture bundle tool

**Goal:** DESIGN §6, deterministic forever, plus the fixture bundle that unblocks R1.

**In scope**
- `paginate/engine.py` implementing §6 steps 1–7 exactly (incl. verse rules and the 1.25×max stanza cap); emits page dicts + `structure.json` content; `schemas.validate` on every output.
- Golden tests: run pg35 through P0; commit the resulting `pages/` word-count vector + first/last 40 chars of pages 1, 2, N as goldens (not full text in goldens — the fixture source is already committed; goldens assert stability). Property tests: no page except chapter-finals `< min`; none `> 1.25×max`; joined pages reproduce chapter text byte-exactly (round-trip!); NFC + `\n` normalization proven.
- Synthetic fixtures: verse-heavy chapter; single-paragraph 3000-word chapter (forced sentence-splitting); chapter shorter than `min`.
- `tools/make_fixture_bundle.py`: builds a **complete valid fake bundle** for a tiny synthetic book (6 pages): real P0 output, hand-written schema-valid cast/selection/prompts, `FakeImagegen`-style placeholder plate/cover WebPs, manifest with real hashes → `tools/out/fixture-bundle/`. This is R1's dev diet and S10's verify target.

**Acceptance**
- [ ] Round-trip byte-equality test green (the load-bearing one).
- [ ] Re-running pagination twice yields identical bytes (determinism test).
- [ ] `make_fixture_bundle.py` output passes `schemas.validate` for every file kind; committed under `server/tests/fixtures/bundle/` (small).

---

## Cycle S4 — Job runner + state machine (fake phases)

**Goal:** DESIGN §7.3/§7.4/§11.2 mechanics proven before any real phase exists.

**In scope**
- `bake/job.py` (job model, JSON persistence, state enum per §7.3); `bake/runner.py` (single asyncio worker, directory-scan queue, tick loop, per-unit persistence); `bake/phases/base.py` (phase protocol: `units(job)`, `unit_done(unit)->bool` via artifact existence+parse, `run_unit(unit)`); WoL helper (`subprocess wakeonlan`, guarded by `GPU_WOL_ENABLED`, unit-tested via monkeypatched subprocess); `waiting_gpu` transition on a `GpuUnavailable` exception; unit-retry ladder (3×, 10/60/300s — sleep monkeypatched in tests) → `failed_units`.
- Two fake phases for tests: `fake_flaky` (unit 3 raises twice), `fake_gpu_down` (raises `GpuUnavailable`).
- Admin endpoints from §11.1: `POST /api/admin/books` (P0 inline: ingest+paginate into `work/`), `GET books`/`{id}`, `PUT chapters` (409 guard), `POST jobs/{id}/start|pause|resume`.
- Kill-test as an automated test: run runner in-process, cancel mid-unit, restart, assert resume skipped completed units and total work lost ≤1 unit.

**Acceptance**
- [ ] State-machine transition table tested (legal + illegal transitions).
- [ ] Flaky unit ends in `failed_units` after exhausting retries; phase still completes.
- [ ] `GpuUnavailable` → `waiting_gpu`; tick with service "back" resumes.
- [ ] Kill-test green. `POST /api/admin/books` with the md fixture produces `work/{id}/pages/*` validating against schema.

---

## Cycle S5 — P1 + P2 (mentions, reducer, canonicalize)

**Goal:** cast pipeline per DESIGN §7.1–7.2 against recorded fixtures.

**In scope**
- `bake/tts_client.py`: thin client for TTS `POST /v1/transform/{name}` + `/v1/models/unload` + `/health`; maps TTS error taxonomy per TTS DESIGN §8 (503-class → `GpuUnavailable`; 422 → `UnitFailed`; 400/404/413 → `PipelineBug` which fails the phase loudly). Respx-tested against every code.
- Fixture capture: `tools/capture_tts_fixtures.py` (run manually on-LAN once TTS T5 exists) hitting cast-mentions for 6 pg35 pages + canonicalize for 2 characters, writing `tests/fixtures/tts/*.json`. **Until then**: hand-write schema-valid fixtures (TTS DESIGN §7 schemas) — mark provenance in a fixtures README; replace with captures at first opportunity.
- `bake/phases/p1_mentions.py` (unit = page; artifact `mentions/{page}.json`); `bake/phases/p2_cast.py`: the §7.2 reducer as a **pure function** in `bake/reduce_cast.py` with the full rule set (articles/honorifics list, union-find, co-occurrence guard, major rule, slugging) + canonicalize calls for majors; writes `cast.json`.
- Reducer unit tests: the Weena/Eloi guard; "Mr. Hillyer"/"Hillyer" merge; possessive strip; top-6 rule; slug uniquing.
- gpu-marked live test: P1+P2 over the first 10 pg35 pages against real TTS.

**Acceptance**
- [ ] Full P1→P2 run over fixtures produces schema-valid `cast.json` with the Time Traveller major and a sane alias set (assert membership, not exact strings).
- [ ] Every TTS error code exercised via respx with the correct job outcome.
- [ ] Reducer edge tests green.

---

## Cycle S6 — P3: sequential ledger phase

**Goal:** DESIGN §7.1 P3 with the contiguity-resume rule.

**In scope**
- `bake/phases/p3_ledger.py`: strictly ordered iteration; each call's `prior_ledger` = previous page's stored ledger (page 1: null); options carry `cast_names` from cast.json + `era` from bake config; artifact `ledgers/{page}.json` (verbatim TTS output); resume = first missing ledger, threading from its predecessor; failed unit → gap rule from DESIGN §7.3 (inherit previous ledger + `carry_notes` annotation) applied at **phase end**, not unit time, so late retries can still fill.
- Fixtures: 6 consecutive-page scene-update responses (captured or hand-written to schema; include one `scene_changed: true`).
- Tests: threading order verified via FakeTTS recording (prior_ledger of call N == output N-1); resume-mid-book test; gap-fill test; final merge writes ledgers into `pages/*.json` (per bundle schema — pages gain their `ledger` field here in `work/`).

**Acceptance**
- [ ] Order/threading test green; kill-resume test green (loses ≤1 page).
- [ ] gpu-marked live: first 8 pg35 pages threaded against real TTS, outputs eyeballed into CYCLE-LOG.

---

## Cycle S7 — P4: selection engine

**Goal:** DESIGN §8 exactly, as a pure function with exhaustive tests.

**In scope**
- `selection/engine.py`: `select(scores, structure, params)` implementing steps 1–5; preset table as data; reasons emitted; **input type contains no text fields** (enforce via dataclass — the spoiler invariant made structural).
- Re-selection diff logic (`selection/reselect.py`) per §8: additive, `retired` transitions, `added_in_revision`.
- `bake/phases/p4_select.py` gluing scores from ledgers → engine → `selection.json`.
- Tests: each preset over a synthetic 120-page score field (deterministic seed) with assertions on gap bounds, floor respected, mandatory marks present, precedence tie-breaks; tiny-work rule (<8 pages); pathological all-low-salience book (gaps exceed max_gap, no forced plates); re-selection diff cases (denser, sparser, overlap).

**Acceptance**
- [ ] All engine tests green; property: no two plates closer than min_gap; every plate reason valid.
- [ ] `selection.json` from the fixture pipeline validates against schema.

---

## Cycle S8 — P5: prompt derivation

**Goal:** DESIGN §7.1 P5.

**In scope**
- `bake/phases/p5_prompts.py`: unit = selected page (`status: selected` only); options assembly per TTS DESIGN §7.5 (ledger, present-cast one_lines capped at 4 by mention frequency, era); artifact `prompts/{page}.json` with `derived` verbatim, `edited_prompt: null`, `final_subject_prompt` computed; cover pseudo-plate prompt assembled CPU-side per DESIGN §10 and stored as `prompts/cover.json`; portrait pseudo-prompts if enabled (`prompts/portrait-{slug}.json`).
- Fixtures: 3 illustration-prompt responses.
- Tests: options assembly (cast filtering/capping) unit-tested; pseudo-plate assembly string-tested (no LLM involved); artifacts schema-valid.

**Acceptance**
- [ ] Fixture pipeline now runs P0→P5 end-to-end on the synthetic 6-page book inside one test, producing a `work/` dir whose every JSON validates. (This test becomes the pipeline's regression anchor.)

---

## Cycle S9 — Admin UI v0

**Goal:** DESIGN §11.3 — the wizard, book detail, and the review gate that makes P6 real. Consult the frontend-design skill for baseline restraint; this is a dense workbench, not a showpiece.

**In scope**
- Server: remaining §11.1 admin endpoints (`review` GET/PUTs, `approve` with its refusal rule, `gutendex` proxy, `reselect` stub that runs S7 logic + re-queues P5 for new plates).
- Admin UI screens per §11.3: Books list + New Book wizard (Gutendex search, paste/upload, metadata+era, style picker reading `styles.json` w/ static sample thumbs committed to repo, density radio, portraits toggle); Book detail (phase/state, warnings, failed_units, chapter editor gated pre-P1, job controls); Review (plates table: page, reason, salience, beat, editable prompt, include toggle; cast panel editable; cover/portrait pseudo-plates; Approve w/ count confirmation); Post-render view stub (thumbs appear after S10; regen button wired to endpoint even if endpoint lands in S10 — feature-flag it).
- `approved` transition wired: approve → job advances (P7 will no-op until S10; state machine already tolerates a phase with zero implementation? No — add a `render_pending` guard: if imagegen client is the Fake, P7 runs with FakeImagegen so the flow is demo-able end-to-end pre-S10).
- Playwright (or Vitest+RTL, executor's call recorded in CYCLE-LOG) smoke: wizard → fixture md book → watch fake phases → edit a prompt → approve.

**Acceptance**
- [ ] Human can run the entire fixture book from wizard to approved (FakeImagegen plates) in a browser with no curl. Screenshots or a screen-recording note in CYCLE-LOG.
- [ ] Approve refuses when a selected plate lacks a prompt (test).
- [ ] Prompt edit persists into `prompts/{page}.json.edited_prompt` and recomputes `final_subject_prompt` (test).

---

## Cycle S10 — P7 render + P8 publish + verify tool

**Goal:** real pixels, immutable bundle. **First step of this cycle: read the imagegen-service repo and write `docs/adr/0011-imagegen-api.md` recording its actual endpoints/params and the client mapping** (DESIGN §10 lists assumed capabilities; verify, don't guess).

**In scope**
- `render/imagegen.py`: `ImagegenClient` protocol + `FakeImagegen` (deterministic placeholder PNG, prompt-hash burned in) + real client per ADR-0011; health check; `GpuUnavailable` mapping.
- `bake/phases/p7_render.py`: units = approved plates + cover + portraits; **pre-phase: TTS unload call + require success** (ADR-0009); wrapped/negative assembly per §10; PNG → derivatives (Pillow WebP pipeline w/ `.src.sha256` sidecars, idempotent); per-plate `render` metadata; regen endpoint (`POST …/plates/{id}/regen`, new seed, `-rN` suffix post-publish).
- `bake/phases/p8_publish.py`: assemble `library/{id}` from `work/`; manifest build (sha256 every file, `reader_required` globs per §4.3); **publish integrity guard** (§4.4: existing pages must be byte-identical, else refuse); revision bump logic; `meta.bake` pinning (TTS `/v1/transforms` versions, model tags from TTS health, git describe).
- `tools/verify_bundle.py`: standalone validator — every schema, every manifest hash, every `reader_required` file present, selection↔prompts↔images cross-references consistent, retired plates' files still present. Exits nonzero on any failure. Run against the S3 fixture bundle in tests.
- Tests: full pipeline P0→P8 on the synthetic book with FakeImagegen inside one test → `verify_bundle` green; integrity-guard refusal test (mutate one page byte, attempt republish); derivative idempotency.

**Acceptance**
- [ ] Synthetic-book end-to-end test green with verify_bundle passing.
- [ ] gpu-marked: render 2 real plates via real imagegen on the LAN; note VRAM sequencing observed (TTS unloaded first) in CYCLE-LOG.
- [ ] ADR-0011 written from the real API.

---

## Cycle S11 — Library + checkout API

**Goal:** DESIGN §11.1 library group.

**In scope**
- `GET /api/library`, `GET /api/library/{id}/manifest`, `GET /api/library/{id}/files/{path}` with path-traversal guard (resolve + prefix check — test with `../` attempts), ETag=sha256 + `If-None-Match` 304s, correct content-types (json/webp/png).
- Serve reader PWA build at `/` and admin at `/admin` (static mounts).
- Tests: traversal rejected; 304 flow; library listing shape.

**Acceptance**
- [ ] From another machine on the LAN: fetch manifest, fetch every `reader_required` file of the fixture bundle by script, hashes match manifest.

---

## Cycle S12 — Sync API

**Goal:** DESIGN §12 exactly.

**In scope**
- `sync/merge.py`: pure annotation merge (union-by-id LWW w/ tombstones) + positions merge (furthest tuple-max, current LWW) — property-tested (merge is commutative, associative, idempotent over doc pairs; write a small property harness, seeded random docs).
- Endpoints: `GET /api/users`; annotations GET/PUT (PUT: merge → backup write → prune to 20 → return merged); positions GET/PUT.
- The three DESIGN §12 conflict examples as named tests.
- `users.json` loader (+ sample committed for dev).

**Acceptance**
- [ ] Property tests green; conflict-example tests green; backups pruned correctly (create 25, expect newest 20).
- [ ] Concurrent PUTs (two async clients, interleaved) never lose an annotation (serialize with a per-(user,book) asyncio lock; test proves it).

---

## Cycle R1 — Reader: shell, shelf, checkout, reading surface, plates

**Goal:** DESIGN §13 core reading against the S3 fixture bundle. Consult the frontend-design skill; reading surfaces reward restraint and typography care.

**In scope**
- `shell/`: `Storage` + `Platform` interfaces; `OpfsStorage` complete; `CapacitorStorage` implemented but exercised in R5; `persistHint()`.
- ESLint network-boundary rule per ADR-0003 (fetch banned outside `sync/` + `shelf/`); wire into `just lint-all`.
- Shelf: library fetch (reachability-guarded), Resident/Available cards, download-with-progress (manifest → hash-verified files → `manifest.local.json`), delta on revision change, remove (keeps annotations).
- Reading surface per §13/ADR-0004: logical-page scroll unit, page-turn nav (swipe + tap zones + keyboard), chapter headers, plate at page top with lightbox zoom, position tracking (page_seq + top-visible char via a lightweight measurement of first visible paragraph offset — approximate is fine, document the approximation).
- Dev mode: `VITE_FIXTURE_BUNDLE=1` loads the committed fixture bundle from static assets so the reader runs with zero server.

**Acceptance**
- [ ] Fixture book: checkout (from a local static serve), then kill the server: open, navigate, view plates, position survives reload. Network tab shows zero requests while reading (verify manually; note in CYCLE-LOG).
- [ ] ESLint rule demonstrably fires on a test violation (include the failing example in a lint test).
- [ ] Hash-verification failure path: corrupt one file mid-download in a test → checkout marks incomplete, retries that file only.

---

## Cycle R2 — Reader: annotations

**Goal:** highlights/notes/bookmarks with byte-solid anchors. **This is the fiddliest client cycle; the anchor math gets the deepest tests in the repo.**

**In scope**
- Render pages as `<p>` per `\n\n` split; selection → UTF-16 offsets into the page's canonical `text` (offset mapper accounts for paragraph splits; single module `annotations/anchors.ts` with pure functions `domRangeToAnchor` / `anchorToDomRange`).
- Anchor tests: multi-paragraph selections, selections starting/ending at paragraph edges, emoji/astral-plane characters (UTF-16!), verse pages with internal `\n`.
- UX per §13: selection bar (4 colors, note sheet, copy), bookmark toggle, annotations list w/ jump, render highlights as spans (overlapping highlights: later-on-top, simple).
- Local persistence per §14 namespacing; tombstone on delete.

**Acceptance**
- [ ] Anchor round-trip property test: for N random ranges over fixture pages, `anchorToDomRange(domRangeToAnchor(r))` selects identical text.
- [ ] Astral-character fixture test green.
- [ ] Highlight created on page X survives app reload and renders at the same characters.

---

## Cycle R3 — Reader: sync client + profile picker

**In scope:** first-run profile picker from `GET /api/users`; settings switcher; sync engine (triggers per §13: foreground, book-close, 10-min, manual) doing full-doc PUT/GET per §12 with reachability guard; merged-doc adoption (server response replaces local doc atomically); positions sync incl. furthest/current semantics + "jump to furthest" chip; sync-status indicator.

**Acceptance**
- [ ] Two browser profiles against a dev server: annotations created offline on both merge to identical sets on both after sync (scripted Playwright test if practical, else manual with CYCLE-LOG evidence).
- [ ] Furthest-wins behavior demonstrated (read ahead on A, behind on B later → chip on B).

---

## Cycle R4 — Reader: search, cast page, settings/typography

**In scope:** MiniSearch build at checkout completion + persist via `toJSON` + lazy load; search UI → jump + match flash; dramatis personae page + toolbar Cast button with the **furthest-read filter** (ADR-0008 — test it: character first mentioned on page 40 invisible while furthest=30); settings screen (font size 5 steps, light/sepia/dark, Literata/Inter — **vendor both fonts + OFL licenses in repo**, no external font loading, covered by the ESLint boundary + a build check that dist/ contains the woff2s); storage-persist status display.

**Acceptance**
- [ ] Search works with server down; index persists across reloads (no rebuild — assert via timing or a build counter).
- [ ] Cast filter test green.
- [ ] `grep -r "fonts.googleapis\|cdn" reader/dist` empty after build (add as a build script assertion).

---

## Cycle R5 — Capacitor Android + persistence hardening

**In scope:** add Capacitor + Android platform; `CapacitorStorage` wired and exercised; filesystem paths under Directory.Data; back-button/gesture nav mapping; status-bar/immersive polish minimal; verify large-bundle checkout on-device (storage + progress UI); persistence check on app kill/restart; build docs (`reader/BUILDING.md`: SDK versions, `npx cap sync`, signing debug builds). iOS: platform added but **explicitly not polished** (deferred register).

**Acceptance**
- [ ] Physical Android device: checkout fixture (or M1) bundle over LAN, airplane mode, full read/annotate/search session, kill app, reopen — everything intact.
- [ ] `just android-build` (or documented equivalent) produces an installable debug APK.

---

## Milestone M1 — First Full Bake

Run DESIGN §16's checklist verbatim on The Time Machine. This is a human-driven milestone, not an executor cycle; the executor's involvement is fixing whatever it surfaces. File every failure as a NOTES entry; re-run until the checklist closes. Declaring M1 done requires ADR-0007's backup to exist.
