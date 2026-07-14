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
