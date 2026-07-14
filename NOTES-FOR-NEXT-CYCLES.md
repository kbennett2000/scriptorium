# Notes for next cycles

Out-of-scope discoveries and things to pick up later. Add, don't rewrite.

## From S1

### Prerequisites / environment (BUILD-PLAN §0.1) not yet satisfied on this box
S1 needs none of these (all its tests are offline/respx-mocked), but later cycles
and the acceptance-on-a-fresh-clone story do:
- **`just` is not installed.** The `justfile` exists and is correct, but S1 was
  verified by invoking the underlying commands directly (`uv run pytest`,
  `npm run lint`, etc.). Install `just` (it is not listed in §0.1 — add it) before
  relying on `just test-all` / `just lint-all` as the definition-of-done gate.
- **`wakeonlan` is not installed** and the GPU env vars (`TTS_URL`,
  `IMAGEGEN_URL`, `GPU_MAC`, `GPU_WOL_ENABLED`, `SCRIPTORIUM_DATA`) are unset.
  Needed from S4/S5 onward and for M1; `config.py` supplies safe defaults so S1
  runs without them.

### `system-overview.md` is missing from the repo
The kickoff and DESIGN §3 list `system-overview.md` as part of the doc trio
"copied in at S1," and DESIGN §7 header calls its §5 invariants binding. The file
does not exist anywhere on disk, so it could not be copied in. **Non-blocking for
S1:** those invariants are restated in DESIGN §15 (transcribed here as ADRs
0001–0010) and DESIGN §1 Principles, which is what the schemas/ADRs were encoded
from. If the file resurfaces, drop it in the repo root; if it is truly gone,
consider DESIGN §1/§15 the canonical statement of the invariants.

### Dev-only npm advisory (esbuild/vite dev server)
`npm audit` reports one moderate advisory (GHSA-67mh-4wv8-2f99: esbuild dev server
lets any site read dev-server responses) in the transitive `esbuild`/`vite`
dependency of both client scaffolds. It affects only the Vite dev server, not
production builds. The only fix is `vite@8` (a breaking major). Deferred — revisit
when the reader/admin builds are exercised for real (R1/S9); a LAN-only, offline-
first dev posture makes this low-risk meanwhile.

### `pipeline_version` source
`meta.bake.pipeline_version` is specified as a `git describe` string (DESIGN §4.3).
No tag exists yet; the first tag should be created before S10's publish phase so
`git describe` yields something meaningful.

### Deprecation warning in tests
`fastapi.testclient` emits a StarletteDeprecationWarning about httpx. Harmless for
now; if it becomes an error in a future dependency bump, migrate the health tests
to `httpx.ASGITransport` directly.

## From S2

### `system-overview.md` is *still* missing
The S2 pre-dispatch note said it would be copied into the repo root; it was not
(still absent on disk). Non-blocking, as established in S1 — its invariants live in
DESIGN §15/§1. If it truly exists somewhere, drop it in the root; otherwise treat
DESIGN §1/§15 as canonical and stop listing it as required reading.

### Ingestion decisions that later cycles inherit
- **textfile does not strip PG boilerplate** (strip is gutenberg-only, per DESIGN §5.1).
  If a user sideloads a raw Project Gutenberg `.txt` as `kind: text`, the header/license
  stay in chapter text. The S9 admin chapter editor / a "detected as Gutenberg?" hint
  could offer to strip; out of scope for S2.
- **RawBook keeps internal `\n` in paragraphs** (verse-safe, lossless). The paginator
  (S3) must decide reflow/normalization on top of this — it already plans NFC + `\n`
  normalization, which aligns with `ingest.base.normalize_source_text`.
- **RawBook has an internal `era` field** (from markdown front-matter) that is *not* in
  DESIGN's minimal RawBook shape. When S9 builds bake config, wire front-matter `era`
  into the proposed `meta.era` default instead of re-deriving it.
- **Front-matter parser is minimal** (scalar `key: value`, four honored keys, no `pyyaml`).
  If a real book needs list/nested front-matter, add `pyyaml` then.

### pytest default marker filter
`pyproject.toml` now sets `addopts = "-m 'not gpu and not network'"`. A CLI `-m <expr>`
overrides it (e.g. `pytest -m network`, `pytest -m gpu`). Keep new opt-in suites behind
these markers so the default run stays offline/GPU-less.

## From S3

### `system-overview.md` is *still* missing (third cycle running)
Pre-dispatch again asked to copy it into the repo root; `find -iname 'system-overview*'`
returns nothing anywhere on disk, so there is no file to copy — not skipped, *absent*.
**Recommendation: stop listing it as a pre-dispatch step and required reading.** Its §5
invariants are fully realized in DESIGN §1/§15 (ADRs 0001–0010), which the schemas, the
immutability guard, and now the paginator's byte-stability were built from. Treat DESIGN
§1/§15 as canonical unless the file resurfaces.

### Paginator decisions later cycles inherit
- **Verse signal is literally "paragraph contains `\n`"** (§6.5). Because ingestion keeps
  hard-wrap `\n` in prose too (S2 decision), wrapped prose is *also* unsplittable-move-whole.
  Fine today. If a future cycle wants prose reflowed (collapse `\n`→space) it must do so
  *before* pagination and re-hash the `usr-` id — the paginator will then only see genuine
  verse as multi-line. Don't reflow inside the paginator (would break byte-stability).
- **Round-trip is guaranteed via a separator ledger**, not naive `\n\n` joining: at a
  sentence/line split the consumed whitespace has nowhere to live on the page (no trailing
  whitespace, §6.6), so `PaginatedBook` records the boundary separator and
  `reconstruct_chapter()` reinserts it. Any tool that reassembles page text (verify, export)
  must use that, not a blind join, or split paragraphs won't rejoin byte-exactly.
- **Page `id` is 4-digit zero-padded (`^[0-9]{4}$`)** → hard cap of 9999 pages per book in
  v1 (page schema pattern). Real books are ~100s of pages; revisit the schema pattern +
  paginator only if a >9999-page book appears (would need a `bundle_version` bump).
- **`RawBook` → paginator is the P0 seam** (§7.1). The job runner (S4) should call
  `ingest.load` then `paginate`, archive the raw source via `ingest.base.archive_source`,
  and persist `pages/*.json` + `structure.json` as the P0 checkpoint. `RawBook.warnings`
  (boilerplate/chapters) surface on the job there — the paginator itself ignores warnings.

### Fixture bundle is the R1 dev diet + S10 verify target
`server/tests/fixtures/bundle/` is a complete valid bundle (`book_id: usr-ef6cf2047a5e`,
6 pages, 2 chapters, 3 plates + cover + 1 portrait). Regenerate with
`cd server && uv run python ../tools/make_fixture_bundle.py`. Determinism depends on the
installed **Pillow version** (flat-colour PNG/WebP encoding) — if a Pillow bump changes the
image bytes, re-commit the regenerated bundle in that same PR. Selection/cast/prompts are
hand-written to schema now; when S7/S5/S8 land, consider regenerating those sections from
the real engines so the fixture tracks reality.

## From S4

### How S5+ real phases plug into the runner
- **Register phases in the pipeline by `from_state`.** The runner (`bake/runner.py`)
  resolves the phase for a job's current state via `pipeline: list[Phase]` (keyed on
  `from_state`) and transitions the job to `phase.to_state` when all units are done. Each
  `(from_state, to_state)` pair **must be a legal edge** in `LEGAL_TRANSITIONS` or
  `Job.transition` raises. Today the app builds `Runner(cfg, pipeline=[])` in `app.py`'s
  lifespan — S5 replaces `[]` with the real P1/P2 phases (and later cycles append P3…P7).
- **A phase implements three methods** (`bake/phases/base.py::Phase`): `units(job, cfg)`
  (deterministic order), `unit_done(job, cfg, unit)` (True iff the checkpoint artifact
  exists **and** parses — this is the entire resume contract), `run_unit(job, cfg, unit)`
  (writes that artifact; may raise `GpuUnavailable`/`UnitFailed`). `run_unit` may be sync or
  async — the runner awaits it if awaitable, so S5's httpx-based GPU phases can be `async def`.
- **Failure taxonomy is fixed:** raise `GpuUnavailable` for 503-class (→ `waiting_gpu`,
  retried each tick with WoL), `UnitFailed` for 422-class retriable (→ 3× 10/60/300s ladder
  → `failed_units`, phase continues), anything else = bug-class (→ job `failed`). P3's
  "ledger gap" carry-forward (§7.3) is a P3 concern layered on top of `failed_units`, not the
  runner's job.
- **GPU phases must set `is_gpu = True`** so the runner sends WoL + polls the health gate
  before running any unit. The default `gpu_gate` polls **TTS** `/health`; the **render**
  phase (P7) needs an imagegen-health gate instead — pass a different `gpu_gate` for the
  render pipeline, or make the gate per-phase, when S10 lands. Also §7.4: P7 must call TTS
  `POST /v1/models/unload` and require success *before* entering — that unload step is not
  yet implemented (no TTS client until S5); wire it as a render-phase precondition in S10.

### The job record is internal runtime state (no schema)
`jobs/{book_id}.json` has **no JSON Schema** on purpose — it is gitignored runtime state, not
a distributed bundle file. Don't add one just to satisfy "schemas are the source of truth";
that rule governs *interchange* formats (bundle files), which are all still schema-validated.
If a future cycle needs cross-process job introspection beyond `/health`'s summary, prefer a
read model over schematizing the on-disk record.

### `job.id == book_id` (one job per book)
`/api/admin/books/{id}` and `/api/admin/jobs/{id}` address the same record. If v1 ever needs
re-bakes/history (multiple jobs per book), this is the spot that changes — add a job id
distinct from `book_id` and an index; today the 1:1 mapping keeps everything addressable by
`book_id` alone.

### P0 source archival is user-source-only
`POST /books` archives the raw source via `read_source` + `archive_source`, which only works
for `text`/`markdown`/paste sources (they carry their bytes). A `gutenberg` source is
adapter-fetched over the network and is **not** archived by S4's P0 (the `read_source`
`ValueError` is swallowed). When the Gutenberg live path is exercised (M1), archive the
fetched bytes inside the gutenberg flow so provenance (§5.1) holds for pg- books too.

### Test-support lives in `tests/` and is imported top-level
`tests/` has no `__init__.py`, so `tests/fake_phases.py` is imported as `from fake_phases
import …` (pytest prepends the test dir to `sys.path`), not as a relative import. Keep new
shared test doubles there and import them the same way.

## From S5

### `cast_running` was added to the state machine (approved deviation)
DESIGN §7.3 gave P1/P3/P5/P7 a `*_running` GPU state but **not** P2, so P2's
`cast-canonicalize` (a GPU call) could not park on `waiting_gpu`. We added
`cast_running` (chain `… mentions_done → cast_running → cast_done …`, `cast_running ∈
GPU_STATES`). If `system-overview.md`/DESIGN ever resurfaces and is treated as canonical,
reconcile it to include `cast_running`. The state list is now: created, ingested,
mentions_running, mentions_done, **cast_running**, cast_done, ledger_running, ledger_done,
selected, prompts_running, prompts_draft, in_review, approved, rendering, published.

### The "enter the running state" pattern for GPU phases
The runner can only park on `waiting_gpu` from a state in `GPU_STATES`, so a GPU phase's
`from_state` must be a `*_running` state. A job coming off a rest/`*_done` state therefore
needs a **CPU "enter" phase** to move it onto the running state first. S5 has two:
`MentionsEnter` (`ingested → mentions_running`, zero units — pure marker) and `CastReduce`
(`mentions_done → cast_running`, carries the actual CPU reduce). **P3/P5/P7 need the same
shape:** a CPU step onto `ledger_running`/`prompts_running`/`rendering`, then the GPU phase.
(P3 also needs strict page contiguity — §7.3 — layered on top.)

### TTS client + error taxonomy are the reusable GPU-call surface
`bake/tts_client.py` (`TtsClient(cfg)`, async) is the one place the TTS taxonomy is mapped:
503/conn → `GpuUnavailable`, 422 → `UnitFailed`, 400/404/413/401/500 → `PipelineBug`
(new bug-class exception in `phases/base.py` → job `failed`). P3/P5 should call it the same
way (`scene-update`, `illustration-prompt`). `unload_models()` is implemented and tested
now but **unused until P7/S10**, which must call it (and require success) before rendering
(§7.4). `health()` exists too; the runner's own `default_gpu_gate` still probes `/health`
independently (left untouched — the S4 runner is load-bearing).

### `_TRANSFORM_TIMEOUT_S` is a hardcoded constant (candidate Config field)
`tts_client._TRANSFORM_TIMEOUT_S = 120.0` (LLM calls are slow) and `_QUICK_TIMEOUT_S = 15.0`
(health/unload). There is still no TTS-timeout `Config` field; promote them if a slow model
or a big page needs tuning. (Same note as S4's "no dedicated TTS timeout field".)

### TTS fixtures are hand-written — replace with real captures
`server/tests/fixtures/tts/**` were authored by hand (TTS unreachable from the box). Run
`tools/capture_tts_fixtures.py` on the LAN (TTS T5 up, `TTS_URL` set) to overwrite them with
genuine captures, and run the `-m gpu` `test_cast_live.py` to paste a real cast summary into
CYCLE-LOG. S6/S8 (P3 ledger, P5 prompts) will want the same capture-tool treatment for
`scene-update` / `illustration-prompt`. Tests assert shape only, so re-captures stay green.

### Reducer intermediates vs. the published cast contract
`reduce_cast` returns groups **with** `is_person` and `descriptors`; those are written to the
work-only `cast/groups.json` and are deliberately **absent** from `cast.json` (per that
schema's top-level note). `cast.json` is (re)assembled from `groups.json` + the per-major
`cast/canon/{slug}.json` after every canonicalized major, so it is always schema-valid and a
kill mid-P2b loses ≤1 unit. Minors (and un-canonicalized/failed majors) get
`visual_description: null`, `one_line: ""`, `tags: []`, `portrait: null`. Portraits are P7.

### Major rule interpretation (pin if it ever matters)
`major` = person groups with ≥3 `mention_pages` **or** the top-6 persons by page count,
**whichever set has more members** (tie → the ≥3 set). Non-persons are never auto-major.
Both branches are pinned by `test_reduce_cast.py`. For tiny casts (<6 persons) the top-6
branch makes nearly everyone major — that is the spec's literal behavior, not a bug.

## From S6

### The "trailing pseudo-unit" pattern for a phase-end finalize (reusable)
The S4 runner has **no post-units / finalize hook** — `advance_job` runs the units loop then
immediately `transition(to_state)` — and it is load-bearing (outside every cycle's scope
fence). When a phase needs work that must run **once, after all real units, only if the phase
actually completes** (P3's gap-rule merge into `pages/*.json`), express it as a **trailing
pseudo-unit** appended to `units()` (P3 uses `id="merge"`, a non-numeric id that can't collide
with a page id). The runner reaches it only after every prior unit has succeeded or
ladder-failed, and parks on `waiting_gpu` *before* it on a 503 — giving exactly "phase end, not
unit time." Its `unit_done` should be an idempotent completion check (P3: "every page carries a
`ledger`"). P5's prompt assembly, if it ever needs a post-pass rollup, can reuse this shape
rather than touching the runner.

### P3 threading: generation vs. the merged gap ledger (don't conflate them)
Two different "prior ledgers" exist and must stay distinct: (1) during **generation**, a page's
`prior_ledger` is the last *successful* stored `ledgers/*.json` before it — so a gap page is
skipped over and the next real page threads from the last real ledger; (2) the **merge** writes
a permanently-failed page's slot in `pages/*.json` as an inherited copy of its predecessor +
`carry_notes += " [ledger gap]"`. Generation never reads the inherited copy. If P4/P5 read
ledgers, read them from `pages/*.json` (the merged, gap-filled view), not `ledgers/*.json` (the
raw, possibly-sparse artifacts).

### Page ledgers now live on `pages/*.json`; `ledgers/*.json` are raw artifacts
P3 stores each raw `scene-update` output at `work/{id}/ledgers/{page}.json` (the resume
checkpoint) and, at phase end, merges the effective ledger onto `work/{id}/pages/{page}.json`
under the `ledger` key (`page.schema.json` already permits it; validated as kind `"page"`). P4
selection consumes only `scene_changed` / `visual_salience` (numbers + booleans — the spoiler
invariant); P5 prompts consume the full ledger. `cast_names` for `scene-update` come from
`cast.json` `name`s (cap 40); `era` from `bake_config`.

### `scene-update` fixtures are hand-written too (same convention as S5)
`server/tests/fixtures/tts/scene-update/*` were authored by hand (TTS unreachable). The capture
tool now threads `scene-update` over 6 pages; run it on-LAN to overwrite, and run
`test_ledger_live.py` (`-m gpu`) to paste a real per-page ledger summary into CYCLE-LOG. Tests
assert shape/threading only, so re-captures stay green.

## From S7

### `selection/reselect.py` is standalone until a revision re-bake wires it in
The P4 phase (`bake/phases/p4_select.py`) only ever writes a **fresh** `selection.json` (all
plates `selected`, `added_in_revision: 1`) — the `ledger_done → selected` hop has no notion of a
prior revision. The re-selection diff (`selection/reselect.py`, fully unit-tested) is where a
density-knob re-turn merges a fresh run against the existing selection (retiring rendered plates,
preserving manual entries, bumping `added_in_revision`). Wire it in wherever revisions are bumped
— the re-bake / publish path (S10-ish), not inside a bake phase. One reading baked into reselect
and flagged in CYCLE-LOG for confirmation: a **never-rendered** non-manual plate (`selected`/
`approved`) not re-chosen is **dropped**, so a human `approved` on an unrendered plate is
discarded on a re-turn. Revisit if the review UX should instead retire (tombstone) approvals.

### P4 reads scores only from `pages/*.json`; the input type is the spoiler boundary
`select()` takes `PageScore` = `{seq, page_id, chapter, scene_changed, visual_salience}` — numbers
and booleans and the id only, a frozen dataclass. This is the structural enforcement of the
spoiler invariant: no text field can reach selection, so it cannot look ahead into content (score
lookahead is fine). A test pins the exact field set. When P5/P7 need the *full* ledger they read
`pages/*.json` directly; they must not route text through the selection types.

### Fill window is intersected with `min_gap` (engine interpretation)
DESIGN §8 step 3's fill window `(last+1 … last+max_gap)` is intersected with the `min_gap`
constraint (`[last+min_gap, min(last+max_gap, next_anchor−min_gap)]`) so the "no two plates
closer than min_gap" acceptance property holds over *all* plates, fills included. Safe because
every preset has `max_gap ≥ 2·min_gap`. If a future preset breaks that ratio, re-derive the
window bounds. The S10 verify tool should treat `min_gap`/`floor`/valid-reason as invariants,
not exact plate equality (the hand-written `bundle/selection.json` intentionally diverges — see
CYCLE-LOG S7).

### Selection score fixtures: committed synthetic field, not in-test RNG
`server/tests/fixtures/selection/synthetic-120.json` is generated once with `random.Random(4835)`
and committed, so the engine property tests are independent of Python's RNG across versions. Regen
only if you deliberately want a new field (and update the plate counts in CYCLE-LOG S7).

## From S8

### P7 must style-wrap page plates but NOT re-wrap the pseudo-plates
P5 leaves `wrapped_prompt`/`negative_prompt` absent (drafts). At P7, a **page** plate wraps as
`style.prefix + final_subject_prompt + style.suffix` and `negative = style.negative + ", " +
join(derived.avoid)` (DESIGN §10). The **cover/portrait** pseudo-plates already have the style
prefix/suffix baked into `final_subject_prompt` (the §10 formulas include them — see CYCLE-LOG S8
interpretation #1), so P7 must **not** re-wrap them (that would double the style cues). Give the
cover/portrait a negative prompt from `style.negative` alone (their `derived` has no `avoid`
array). Decide P7's wrap dispatch by `page_id` (numeric = wrap; `cover`/`portrait-*` = pass
through, negative-only).

### The style catalog now has a loader (`scriptorium.styles`)
`get_style(style_id)` / `load_styles()` read + schema-validate `data/styles.json`, resolving the
path from the repo root (env override `SCRIPTORIUM_STYLES`) independent of the passed `Config` —
same trick as `schemas.py`, so it works under tests that point `Config.shared_dir` at a tmp dir.
An unknown `style_id` raises `PipelineBug` (bug-class → job `failed`); the admin picker only
offers catalog ids, so a miss is a real misconfiguration. P7 reuses this for the wrap strings.

### `TtsClient.transform_with_meta` + `Job.prompt_warnings` (surfacing TTS warnings)
`transform` still returns only `output` (P1/P2/P3 unchanged); `transform_with_meta` returns
`(output, meta)` via a shared private `_post`. P5 records any `meta.warnings` on the schema-free
`Job.prompt_warnings` dict keyed by page_id. **The TTS §4 contract does not yet define
`meta.warnings`** — this is forward-looking plumbing. S9's review gate should surface
`job.prompt_warnings[page_id]` next to each plate; confirm the real key name once TTS T6 lands.

### Stale bundle prompt fixtures — regenerate at S10
`server/tests/fixtures/bundle/prompts/{cover,portrait-the-clockmaker,0001,0003,0004}.json` predate
the §10 formulas and the TTS §7.5 `derived` shape: their `derived.avoid` is a *string* (not an
array) and they carry a `scene` field; the cover/portrait subjects don't follow the §10 formulas.
They only pass validation because `prompt.derived` is opaque. `test_pipeline_e2e.py` (not these
fixtures) is now the P0→P5 regression anchor. Regenerate the bundle prompts via
`tools/make_fixture_bundle.py` to real P5/§10 output at S10, and have the S10 verify tool assert
prompt schema + cross-refs, not equality with the current stale files.

### The P0→P5 regression anchor is `test_pipeline_e2e.py`
It runs real P0 (`run_p0` on a committed inline synthetic book) + the whole registered
`BAKE_PIPELINE` with generic schema-valid TTS stubs, and validates every schema-bound artifact in
`work/`. Any phase that breaks its artifact contract fails here. Extend it (not replace it) as
P6/P7 land — add the manifest/positions/rendered-prompt artifacts to `_validate_tree` when they
appear.

## From S9a

### S9b (the admin UI) is next and fully unblocked
S9a shipped the server; the follow-up cycle builds `admin-ui/` per DESIGN §11.3 against these
endpoints. A ready spec lives at the bottom of the S9a plan file (`kickoff-scriptorium-sorted-
hennessy.md`, "Deferred to S9b"). Blank slate: no router/data-lib/CSS/test-runner in `admin-ui`
yet. Decisions already made for S9b: **Vitest + RTL + jsdom, stubbed `fetch`** for the smoke test
(Playwright deferred); hand-write API-payload TS interfaces (only the *bundle* shapes come from
`@scriptorium/shared`; the Job/review-payload shapes are not schema'd); add a Vite dev
`server.proxy` `/api`+`/health` → `:8720` (none exists); commit **placeholder** style swatches
(inline SVG is simplest — real rendered samples deferred to M1); optionally static-mount
`admin-ui/dist` at `/admin` (the server does **not** serve it today). The **frontend-design skill
was absent** in the S9a environment — load it in S9b if present, else apply density/restraint
principles directly.

### S10 replaces `p7_render_stub.py` wholesale (and clears `render_stub`)
`bake/phases/p7_render_stub.py` is a **demo** phase — `is_gpu=False`, renders `FakeImagegen`
placeholders, no style wrap, no derivatives, rests at `rendering`. S10 **deletes it** and lands the
real `p7_render.py`: `is_gpu=True` with an enter-split (`approved → rendering` CPU claim, then a GPU
phase), a mandatory pre-phase **TTS unload** (ADR-0009), §10 `wrapped_prompt`/`negative_prompt`
assembly recorded on `prompts/*.json`, the Pillow WebP derivative pipeline (`.src.sha256`
sidecars), per-plate `render` provenance, and `rendering → published` (P8). When the real render
runs it should **clear `Job.render_stub`** (or the UI keeps flagging placeholders). `FakeImagegen`
in `render/imagegen.py` (deterministic Pillow PNG, prompt hash burned in) is the **shared test
double** — keep it; S10 adds the real `ImagegenClient` per the imagegen-service API (ADR-0011).

### The review endpoints assume **pre-publish** semantics
`review_api.py` edits mutate `work/{id}/` in place and are gated to `prompts_draft`/`in_review`
(prompt/selection/cast) or `selected`+review (reselect). None of the immutability guard applies yet
(nothing is published). S10/S11 own the **post-publish** flows the DESIGN table hints at (prompt PUT
"post-publish allowed for regen", reselect's revision bump, the `plates/{id}/regen` endpoint) — do
**not** widen the S9a guards to those states without the additive-revision machinery.

### Manual-added review plates have no prompt until a re-derive
`PUT …/review/selection {add:[page_id]}` writes a `reason:"manual"` selection entry but does **not**
derive its prompt (P5 already ran). So `approve` will refuse a manual add whose page never had a
prompt — that is the intended box-#2 behaviour, and it is how the refusal test is built. To realise
prompts for genuinely-new manual plates, `reselect` (or a re-run) re-queues P5. If S9b wants a
one-click "add + derive", it should call reselect or a future targeted re-derive — not loosen
`approve`. (Removing a plate keeps its prompt file, so include-toggles round-trip for free.)

### New endpoints S9b/S10 consume: `GET /styles` and `GET …/plate-image/{page_id}.png`
`GET /api/admin/styles` returns the `data/styles.json` catalog (via the S8 `load_styles`) — the
wizard's only route to the style list. `GET /api/admin/books/{id}/plate-image/{page_id}.png` serves
a work-dir plate PNG (path-traversal-guarded, admin-only, pre-publish) for the S9b post-render
thumbs; the real reader image serving is the S11 library file server, separate from this.

## From S9b

### S9b is done — `admin-ui/` is now a working workbench (four §11.3 screens)
Built against the S9a endpoints with **no server changes**. Tooling now established in `admin-ui`:
Vitest+RTL+jsdom (explicit imports), a Vite dev `server.proxy` → `:8720`, a hand-rolled hash router
(`src/routes.ts`), a typed fetch client (`src/api/client.ts`) + hand-written API types
(`src/api/types.ts`). The reader can copy this shape when R1 needs a test runner / network client
(but the reader's calls stay fenced to `sync/`+`shelf/` — admin-ui is deliberately unfenced).

### Missing GET endpoint: current chapter paragraphs (chapter editor is crippled without it)
`PUT /api/admin/books/{id}/chapters` replaces chapters, but there is **no endpoint to READ** the
current chapter/paragraph text, so the S9b chapter editor is a raw JSON re-submit (you can't load
what's there to edit it). Add a `GET /api/admin/books/{id}/chapters` (or fold structure+page text
into the book detail payload) so a real chapter-break editor is possible. Low priority (pre-P1 only).

### S10 replaces the post-render stub UX, not just the phase
`PostRender.tsx` is feature-flagged (`POSTRENDER_ENABLED`, `src/config.ts`) and shows a
"placeholder render" banner + a **disabled Regen** button. When S10 lands the real
`POST …/plates/{page_id}/regen`, wire the Regen button to it and drop the disabled state + the
stub banner (gate the banner on `job.render_stub` instead of always-on). S10 clearing `render_stub`
(per From S9a) is what flips that banner off.

### Style swatches are placeholders (inline SVG); commit real samples at M1
`src/components/StyleSwatch.tsx` derives an abstract SVG from the style id. DESIGN §11.3 wants
"pre-rendered static samples committed to the repo" — produce those at M1 (one small image per
style id under `admin-ui/public/` or `data/`) and swap the swatch to render them.

### The seed helper is a dev double for the no-GPU acceptance walk
`tools/seed_review_book.py` puts a book at `prompts_draft` from the fixture bundle so the review →
approve → stub-render walk runs with zero GPU/TTS. It's not part of the pipeline; keep it working as
the fixture bundle evolves (it copies pages/structure/selection/cast/prompts and resets plate
statuses to `selected`). When S10 regenerates the bundle prompts (From S8), the seed still works.

### Serving `admin-ui/dist` at `/admin` is still not wired
The server does not `StaticFiles`-mount the built admin UI; dev relies on the Vite proxy. If you
want the i5 server to serve `/admin` in production, add the mount in `app.py` (a server change,
deliberately out of S9b's UI-only scope). `admin-ui/dist/` is gitignored.

## From S10a

### S10b is the rest of S10 (publish + verify) — the binding scope
Build `bake/phases/p8_publish.py` (`rendered → published`): assemble `library/{id}` from `work/`
(copy PNGs + derivatives + `retired` plate files), write `manifest.json` (sha256 every file +
`reader_required` globs per §4.3), the **publish integrity guard** (§4.4 — existing published
`pages/*.json` must be byte-identical or refuse), revision bump, and `meta.bake` pinning (TTS
`/v1/transforms` versions, model tags from TTS `/health`, `git describe`). Add `Config.library_dir`
(does not exist yet). Plus `tools/verify_bundle.py` (all schemas / all hashes / `reader_required`
present / selection↔prompts↔images cross-refs / retired files present / nonzero exit) and extend
`test_pipeline_e2e` to **P0→P8** with the integrity-guard-refusal + cross-publish-idempotency boxes.
The §4.2 bundle layout P7 already writes (`images/plates|cover|portraits` + `web`/`thumbs`) is
publish-ready — P8 is largely a validated copy + manifest.

### Regen is split across S10a/S10b by design
S10a's `POST …/plates/{id}/regen` handles the **pre-publish** case only (re-render into `work/`, new
seed, `render` provenance bump; **409 if published**). S10b adds the **post-publish additive** path:
write a new `…-rN.png` file, update `prompts/{id}.render` + the selection entry, bump the manifest
revision — never mutating a published file (§4.4). Reuse `render_plate()` (already factored).

### The render GPU gate is in-phase, not runner-level (possible refactor)
The runner's `default_gpu_gate` probes **TTS** `/health` for every `is_gpu` phase; P7 also needs
imagegen. S10a handles this inside the phase (the `__unload__` unit does TTS-unload + imagegen
`health()`, raising `GpuUnavailable` to park). Fine as-is, but if more render-only gating is wanted,
consider making `gpu_gate` phase-aware (pass the phase) so it can probe imagegen for `p7_render`.

### imagegen-service size PR must be merged + deployed before real 832×1216
`RealImagegenClient` sends `width`/`height`, but only imagegen-service **PR #13** (add width/height,
default 1024²) makes the service honour them. Until it is merged and the service redeployed on the
GPU box, a real render silently returns 1024² — the gpu-marked `test_render_live` asserts 832×1216,
so it will catch a stale deployment. FakeImagegen (all offline tests) honours the sizes regardless.

### admin-UI Regen + `rendered`-state wiring is deferred to S10b
S9b's `PostRender.tsx` gates on `state ∈ {rendering, published}` and disables Regen. With the new
`rendered` state and the live regen endpoint, S10b should: include `rendered` in that gate, enable
the Regen button (`POST …/plates/{id}/regen`), and drop the placeholder banner (gate it on
`job.render_stub`, which real render now leaves False). Out of S10a's server-only scope.

### Live checkpoint still pending (TTS degraded)
The S5-era live checkpoint + the S10 gpu-marked render test remain unrun: on this box TTS answered
`/health` but reported `degraded`/`ollama_reachable:false` (no transforms possible), and imagegen is
on the GPU box (unreachable from here). When TTS/ollama is healthy on the LAN with imagegen up, run
`capture_tts_fixtures.py` + `uv run pytest -m gpu` (cast/ledger/prompts/**render** live) and paste
summaries into CYCLE-LOG.

## From S10b

### gpu-marked live render is pending on a stale imagegen deploy (restart needed)
The LAN is green (TTS + ollama up, imagegen `comfyuiReachable:true`) and the live render runs
end-to-end, but the **deployed imagegen-service predates PR #13**: it returns 1024² even for an
explicit `{width:832,height:1216}` request (HTTP 200, no 422). The fix is already on disk
(`cf0f0a6`, `setNodeSize`); it needs a **service restart** (`sudo systemctl restart
imagegen-service` on the GPU box — sudo/human; a shared-service restart, not something the headless
cycle does unauthorized). After the restart, re-run `TTS_URL=… IMAGEGEN_URL=… uv run pytest -m gpu
tests/test_render_live.py -s` — it asserts 832×1216 and will go green (it correctly caught the stale
deploy this cycle). This supersedes the S10a "TTS degraded" reason — TTS/ollama are healthy now.

### Post-publish `-rN` variant resolution is a reader (S11) concern
Post-publish regen writes an additive `…/{page}-r{revision}.png` (+ web/thumb) beside the untouched
original and bumps the revision; the prompt schema's `render` block is `additionalProperties:false`,
so there is **no current-variant pointer** — the convention is **highest `-rN` wins**, derivable
from filenames + manifest. `verify_bundle` tolerates the variants. When S11 builds checkout/serving,
implement that resolution (and delta-sync may prune superseded variants locally, §4.4).

### reselect → re-publish (revision re-bake) is still unwired
`selection/reselect.py` remains standalone. The publish integrity guard + revision bump are now in
place (`p8_publish.publish_bundle` bumps past the prior library revision), so the re-bake path a
density-knob re-turn should trigger — reselect → P5(new)→P6→P7→**P8 re-publish** — can be wired
where revisions are bumped. The guard will (correctly) refuse if a re-bake changes any published
page's bytes. Confirm the "drop never-rendered non-manual plates" reading (flagged From S7) when it
is wired.

### meta.bake pinning is best-effort; richer per-bake capture is a possible follow-up
`p8_publish._pin_bake` queries TTS `/v1/transforms` + `/health` (and imagegen `/health`) at publish
time and falls back to non-empty placeholders offline. It does **not** capture the exact transform
versions used *during* the bake (P1/P3/P5 discard the `meta` they receive). If provenance fidelity
matters, thread the versions from `transform_with_meta` onto the job during the bake and read them
here instead of re-querying at publish.

### The fixture bundle is now real P8 output (new identity + regeneration command)
`server/tests/fixtures/bundle/` is `usr-ce8f5ebd29d0` ("The Winter Quay", cast slug `wanderer`, 2
plates) produced by the real pipeline. Regenerate with `cd server && uv run python
../tools/make_fixture_bundle.py` (byte-reproducible — frozen clock + pinned `meta.bake` +
deterministic FakeImagegen; `git diff --exit-code` after). The shared driver is
`server/tests/_pipeline_build.py` (imported by both the tool and `test_pipeline_e2e`). Any phase
change that alters an artifact means regenerating + re-committing the bundle in the same PR. The S7
`selection.json` min_gap divergence and the S8 stale-prompt divergence are **cleared**.

## From S11

### The manifest glob-matcher is now triplicated — a candidate for a shared util
`_matches_any` (the `/**` / `/*` / exact dialect) now lives in three places:
`bake/phases/p8_publish.py`, `tools/verify_bundle.py`, and `library/checkout.py::matches_any`. All
three must stay in lockstep. If a fourth consumer appears, promote it to a small shared module (e.g.
`scriptorium/bundle_globs.py`) and have p8/verify import it — deferred now to avoid touching the
sacred publish/verify paths in a serving cycle.

### Listing `total_bytes_reader` (resolved) can differ from the stored manifest field after a regen
`GET /api/library` reports `total_bytes_reader` over the **resolved** reader set
(`checkout.resolved_total_bytes` — current `-rN` variants only), i.e. exactly what the reader
downloads. P8's stored `manifest.total_bytes_reader` (`build_manifest`) still sums **all**
reader-required matches, so after a post-publish regen it counts the superseded base too and the two
numbers diverge (the stored one is an upper bound). Harmless today (fixture has no variants → both
41812). If you want them identical, recompute P8's stored total over the resolved set in
`build_manifest`/`regen_published_plate` — a P8 change that forces a fixture regen, so out of S11's
serving scope.

### Reader-side `-rN` resolution must mirror `library/checkout.py` (S12/R1)
The server exposes every variant via the files endpoint and lists the resolved size, but the client
decides what to fetch. The TS reader's `sync/` must implement the **same** highest-`-rN`-wins rule
(group by `(dir, base_stem, ext)`, strip a trailing `-r<digits>`, keep max N; base = revision 1) so
delta-sync downloads exactly one current image per plate and may prune superseded variants locally
(§4.4). `server/src/scriptorium/library/checkout.py` is the reference implementation — port its
`_variant_key` logic verbatim. Note the theoretical ambiguity: a portrait slug literally ending
`-r<digits>` would be misparsed (page-ids are 4-digit numerics, so plates are safe); guard only if a
real slug ever collides.

### Static SPA mounts have no deep-link fallback beyond `html=True`
`app._mount_static` uses `StaticFiles(..., html=True)`, which serves `index.html` for a directory
request but **404s an unknown sub-path** — so a hard refresh on a client-routed deep link (e.g.
`/book/pg-35/read`) under the reader mount at `/` will 404 instead of loading the SPA shell. Fine for
the hash-router admin UI and for v1; when the reader uses path-based routing, add an SPA catch-all
(serve `index.html` for non-asset 404s under the mount) — a small custom StaticFiles subclass or an
exception handler. Deferred (no reader routing exists yet). Also: the mounts are decided at **import
time** from env; a deployment that builds `dist/` after the server process starts must restart it.

### Live acceptance ran against localhost, not a second LAN machine
S11's acceptance box says "from another machine on the LAN." I verified the checkout contract with a
real `uvicorn` + scripted client over `127.0.0.1:8799` (18/18 reader files sha256-verified, transfer
== `total_bytes_reader`, ETag/304, traversal 400) — functionally identical to a LAN fetch (same ASGI
path), but a true cross-host run (and a real pg-35 bundle rather than the `usr-…` fixture) is still
worth doing once a reader box exists. The offline `test_library_api.py` fully covers the contract.

## From S12 (sync API)

### Reader-side merge (R3) must mirror `sync/merge.py` bit-for-bit
The server is authoritative, but R3's sync engine adopts the server's merged doc *and* may merge
locally before PUT, so the TS merge must match `server/src/scriptorium/sync/merge.py` exactly:
annotations = union by `id`, LWW by `modified` (ISO **string** compare — do not parse to Date, the
strings are already UTC and lexically ordered), tombstones merge identically (a later delete beats an
earlier edit and vice-versa — deletion can lose); positions `furthest` = tuple-max on
`(page_seq, char)` ignoring time, `current` = LWW. **Port the tie-breaks too** — equal-`modified`
collisions are resolved by a deterministic full-field key (annotations: canonical JSON of the entry;
`current`: `(page_seq, char, device)`); skip them and two clients can diverge on identical
timestamps. Output must be canonical (annotations sorted by `id`) so client/server equality holds.

### Tombstone compaction is still deferred — the 180-day constant is inert
`merge_annotations` keeps **every** tombstone forever; `TOMBSTONE_RETENTION_DAYS = 180` is only a
documented floor a future compactor must honor. Annotation docs therefore grow unbounded across a
book's life (a few hundred entries is fine per §12, so no urgency). When compaction lands it must run
server-side after merge, drop only tombstones older than the retention floor, and stay convergent
(a client offline longer than the floor could resurrect a compacted-away annotation — accept or
lengthen the floor). Not v1.

### Positions have no backup by design; annotations backups are unbounded-in-count-but-pruned
Only annotations get versioned backups (`sync/annotations-backups/{user}/{book}/{ns}.json`, newest 20
kept). Positions are cheap to reconstruct and were intentionally left un-backed-up (DESIGN §12). If a
positions-restore is ever wanted, add a parallel prune-to-N there — trivial, deliberately omitted.

### `GET /api/sync/positions` is household-visible; `PROGRESS_PRIVATE` reserved
No auth and no per-profile restriction on reading another profile's position (DESIGN §12 — the shelf
shows "Amy is on ch. 4"). The `PROGRESS_PRIVATE=false` flag is reserved and **unimplemented**; wiring
it means a config field + a requesting-profile check on the positions GET (and R3 UI to set it).

### users.json admin CRUD is still a §14 stretch goal (not built)
`GET /api/users` is read-only; profiles are hand-edited in `data_dir/users.json` (falls back to the
committed `users/users.sample.json`). Admin-UI CRUD for profiles was descoped from S12; add it as a
small admin cycle if desired. Note the sample ships **inside the package** — a wheel build must
include package data (dev/editable installs read it directly via `Path(__file__).parent`).

### Encoded-`..` rejection code differs by server (both safe)
`{user}`/`{book}` traversal is rejected two ways: the pattern guard returns **400**, but a real ASGI
server (uvicorn) normalizes `..` in the path *before* routing, so a two-segment route simply doesn't
match → **404**. `TestClient` doesn't normalize, so tests see 400. `test_encoded_traversal_never_
escapes` asserts rejection ∈ {400, 404} + no leak rather than a fixed code. Nothing reaches disk
outside `sync_dir` either way (the `is_relative_to` backstop).

## From R1a (reader: shell + shelf + checkout)

### The `-rN` drift guard is `shared/test-vectors/rn-resolution.json` — extend it when variants land
Both `server/src/scriptorium/library/checkout.py` and `reader/src/shelf/resolve.ts` are pinned
against this one vector file (`server/tests/test_rn_vectors.py` + `reader/src/shelf/resolve.test.ts`).
When a real post-publish `-rN` regen bundle exists, add a case built from it so the guard covers
production shapes, not just synthetic ones. If you ever change the resolution rule, change the vector
and BOTH suites move together — that's the point.

### OpfsStorage is only contract-tested via MemoryStorage (jsdom has no OPFS)
`shell/storage-contract.test.ts` pins the `Storage` semantics against `MemoryStorage`. `OpfsStorage`
itself (real `navigator.storage.getDirectory()`) is exercised only in a real browser — do it as part
of **R1b's offline-acceptance run** (checkout the fixture in a browser, kill the server, confirm
reading + zero network). If OPFS behaviour ever surprises us, that's where it surfaces.

### R1b owes: the reading surface, VITE_FIXTURE_BUNDLE, and full offline acceptance — DONE in R1b
R1a stops at Resident. R1b must add: byte-faithful `<p>`-per-`\n\n` text render with verse `\n`
preserved (lock with a rendering test — R2 anchors depend on it); plate-at-page-top + lightbox
(map page_id→`images/web/plates/{page_id}.webp` via `selection.json`); page-turn nav; position
tracking (page_seq + approximate top-visible char — document the approximation); `VITE_FIXTURE_BUNDLE`
zero-server dev mode; and the offline acceptance (open/navigate/plates/position-survives-reload +
DevTools network idle). Plate images come from Storage as bytes → `Blob`/object URL.

### Retired-plate hiding — CLOSED in R1b
A page has a plate iff its `page_id` is in `selection.json` `plates[]`; the image path is by
convention `images/web/plates/{page_id}.webp` (resolved highest-`-rN`). **A `retired` plate keeps its
files** (§4.4), so a naive reader would still show it. R1b's `Reader.tsx` builds its plate set from
`selection.plates[]` filtered to `status !== "retired"`, and a `Reader.test.tsx` case asserts a
retired plate does not render. Done.

### Reader TypeScript floats to 5.9 (from ^5.6.3) — WebCrypto/OPFS need ArrayBuffer copies
`npm install` resolved `typescript@^5.6.3` to 5.9.3, whose `Uint8Array<ArrayBufferLike>` generics make
a plain `Uint8Array` non-assignable to `BufferSource`. `sha256Hex` and `OpfsStorage.writeBytes` copy
into a fresh `ArrayBuffer` before the WebCrypto/OPFS call, and `OpfsStorage.walk` narrows
`FileSystemDirectoryHandle.entries()` locally (not yet in the DOM lib). If the toolchain is pinned to
5.6 later, these copies/narrowings can be simplified but are harmless.

### CapacitorStorage is still a throwing stub (R5)
`shell/capacitor.ts` implements the `Storage` shape but every method throws "implemented in R5" — no
`@capacitor/*` dependency is pulled into the reader yet. R5 (Capacitor build) fills it and wires
`getStorage()` to select it on native platforms.

## From R1b (reader: the reading surface)

### `readerview/pagetext.ts` IS the anchor substrate — R2 must reuse it, not reinvent it
The byte-faithful paragraph math lives here: `splitParagraphs`/`joinParagraphs` (exact inverse on the
`"\n\n"` delimiter, verse `\n` preserved), `paragraphStarts` (`start[i] = Σ len(p_j<i) + 2·i`, UTF-16
code units), `paragraphIndexForChar`. R2's `Selection`/`Range` → anchor mapping must compute offsets
the SAME way (paragraph i's DOM `<p>` starts at `paragraphStarts[i]`; the `"\n\n"` join contributes 2
units between paragraphs). `pagetext.test.ts` is the rendering-lock — extend it, don't fork the math.
**All offsets are UTF-16 code units; never iterate by code point on the offset path** (astral chars
count as 2, consistently). The rendered DOM is `<p>` per paragraph with `white-space: pre-line`.

### Positions are persisted LOCALLY only in R1b — R3 owns merge/upload
`readerview/position.ts` writes `positions/{bookId}.json` (OUTSIDE `books/`, so shelf Remove keeps it)
already shaped to `positions.schema` (`furthest` max-tuple, `current` LWW, `device` = a persisted
`crypto.randomUUID()`). R3's sync client should read these files and feed them straight into the S12
positions merge — the on-disk shape is deliberately the wire shape. R1b does NOT ping the server or
merge; it only reads/writes the local file. `page_seq → page index` uses `index = page_seq - 1`
(seq is contiguous 1-based reading order) with a clamp; revisit if a book ever has non-contiguous seq.

### Edge tap-zones will collide with R2 text selection
`Reader.tsx` nav includes narrow left/right edge tap-zones (`.tap-zone`, 12% width, inset from top/
bottom) kept OUTSIDE the centered text column so they don't block selection. When R2 adds
selection-to-highlight, re-check that a drag starting near an edge isn't stolen by a tap-zone
(and that a tap on the plate/lightbox still works). Keyboard ←/→, Prev/Next buttons, and swipe are the
other nav paths.

### FixtureBundleReader reads the canonical server fixture via glob + `fs.allow`
`VITE_FIXTURE_BUNDLE=1` opens `server/tests/fixtures/bundle/` with no backend, via `import.meta.glob`
(`?raw` JSON inlined, `?inline` images emitted as local assets). It needs the `server.fs.allow` entry
in `reader/vite.config.ts` (dev server only; `vite build` reads disk directly). It is a **dev
convenience** — the genuinely zero-network read path is `StorageBundleReader` over OPFS. It is
dynamically imported so the eager glob (and the fixture bytes) stay out of the prod bundle. If a real
`-rN`-variant fixture is ever added, teach `FixtureBundleReader.imageUrl` to run `resolveReaderFiles`
over the fixture manifest (today it's a plain path lookup because the fixture has no variants).

### `StorageBundleReader` mints object URLs — callers MUST `dispose()`
Image bytes → `Blob({type:"image/webp"})` → `URL.createObjectURL`, cached per logical path and revoked
in `dispose()`. `Reader.tsx` calls `dispose()` on unmount. Any future surface that constructs a
`StorageBundleReader` (search result previews, cast portraits in R4) must do the same or it leaks blob
URLs. Blob MIME is hardcoded webp (correct for `images/web/**`/`images/thumbs/**`); if the `.png`
originals are ever served, derive the type from the extension.
