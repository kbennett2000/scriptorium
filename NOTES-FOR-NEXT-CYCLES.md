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
