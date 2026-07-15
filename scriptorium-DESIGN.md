# Scriptorium — Design Document

**Status:** Approved for build — 2026-07-13
**Owner:** Kris Bennett / Twelve Rocks LLC
**Repo:** `scriptorium` (monorepo). Companion service: `text-transform-service` (separate repo, separate DESIGN/BUILD-PLAN).

Scriptorium turns books into illuminated, offline-readable bundles: a **bakery** (batch pipeline on the i5 server, GPU work delegated over the LAN) and a **reader** (Capacitor/PWA client that owns books entirely on-device after checkout). Read `system-overview.md` first; its §5 invariants are binding here and restated as ADRs in §15.

---

## 1. Principles

1. **Local-first.** Bake-time requires the LAN and the 5070 awake. Read-time requires nothing — no internet, no LAN, no server process. Desktop and mobile are the same client in different shells.
2. **Immutable bundles, mutable margins.** Published text/structure never changes; annotations are the only mutable layer, namespaced per user, synced opportunistically.
3. **Review-gated rendering.** A human approves every shot list before pixels are made.
4. **Causal generation.** Nothing shown for page N was derived from pages > N. No spoilers, structurally.
5. **Fallback is time.** No API keys anywhere in this repo. GPU unavailable ⇒ pause, resume.
6. **Resumable everything.** Any process may die at any moment and lose ≤ one unit of work.
7. **Household multi-user.** Profiles without passwords (LAN trust), per-user annotations and positions.

## 2. Topology

| Piece | Runs on | Talks to |
|---|---|---|
| `server/` — bakery orchestrator, library, sync, admin UI | i5-3540, Ubuntu Server | `text-transform-service` (5070:8712), `imagegen-service` (5070), filesystem |
| `reader/` — client app | Android/iOS (Capacitor), desktop (installable PWA served from the i5) | server APIs only when reachable; otherwise nothing |
| `shared/` — JSON Schemas + generated TS types for every bundle/sync file | consumed by both | — |

`imagegen-service` is Chronicle's existing service, **unmodified**. Its exact API is verified against its repo at cycle S10; until then it lives behind an interface (§10).

## 3. Repo layout

```
scriptorium/
  system-overview.md, scriptorium-DESIGN.md, scriptorium-BUILD-PLAN.md   # this trio, copied in at S1
  docs/adr/                      # ADRs (§15 seeds them)
  shared/schemas/*.schema.json   # single source of truth for all file formats
  server/                        # Python 3.12, FastAPI, uv (house pattern)
    src/scriptorium/
      app.py, config.py
      ingest/        # adapters + normalizer
      paginate/
      bake/          # orchestrator, phases, job store
      selection/     # pure functions
      styles/
      render/        # imagegen client, derivatives
      library/       # bundles, manifests, checkout
      sync/          # annotations, positions, backups
      users/
    tests/
    deploy/          # systemd units
  reader/            # Vite + React + TypeScript
    src/
      shell/         # capacitor + pwa storage abstraction
      shelf/ readerview/ annotations/ sync/ search/ settings/
    android/ ios/    # capacitor platforms (added in R5)
  admin-ui/          # Vite + React + TS, served by server/ (kept out of reader/ deliberately)
  tools/             # fixture builders, dev scripts
```

**Data directory on the i5** (`SCRIPTORIUM_DATA`, default `/var/lib/scriptorium`):
```
data/
  library/{book_id}/           # published bundles (immutable + additive)
  work/{book_id}/              # bake workspace (mutable until publish)
  sync/annotations/{user_id}/{book_id}.json
  sync/annotations-backups/{user_id}/{book_id}/{iso_ts}.json   # last 20 kept
  sync/positions/{user_id}/{book_id}.json
  users.json
  styles.json
  jobs/{job_id}.json
```
**This directory is the only irreplaceable data in the system.** ADR-0007 requires an off-box backup (restic or rsync-to-elsewhere) before M1 is declared done; the mechanism is the human's choice, the requirement is not.

## 4. Bundle format (the contract everything hangs on)

All JSON files validate against `shared/schemas/`. Schemas are written first (S1) and are versioned via a `bundle_version` integer (starts at 1).

### 4.1 Identity

- Gutenberg books: `pg-{gutenberg_id}` (e.g., `pg-35`).
- User-supplied: `usr-{first 12 hex of sha256 of normalized source text}`.
- Ids are permanent. Re-ingesting the same source yields the same id; the server refuses to overwrite an existing published bundle with different page content (integrity check at publish).

### 4.2 Layout

```
library/pg-35/
  meta.json
  structure.json
  pages/0001.json … 0NNN.json      # zero-padded 4-digit seq
  cast.json
  selection.json
  prompts/0007.json …              # only for pages ever selected
  images/plates/0007.png           # SDXL native (832×1216)
  images/web/plates/0007.webp      # reader derivative (≤1080w, q80)
  images/thumbs/plates/0007.webp   # 320w
  images/cover.png, images/web/cover.webp, images/thumbs/cover.webp
  images/portraits/{slug}.png + web/thumbs variants     # optional (dramatis personae)
  manifest.json
```

### 4.3 File schemas (abridged here; full JSON Schema lives in `shared/schemas/` and is normative)

**meta.json**
```json
{ "bundle_version": 1, "book_id": "pg-35", "revision": 3,
  "title": "The Time Machine", "author": "H. G. Wells", "language": "en",
  "source": { "kind": "gutenberg", "gutenberg_id": 35, "retrieved_at": "…" },
  "era": "1890s England",
  "style_id": "engraving", "density_preset": "classic", "portraits_enabled": true,
  "bake": { "completed_at": "…",
    "transform_service": {"url_host": "…", "transforms": {"scene-update": "0.1.0", "…": "…"}},
    "models": {"llm": "qwen3:8b", "imagegen": "sdxl-…(as reported)"},
    "pipeline_version": "…git describe…" },
  "stats": { "pages": 118, "words": 32700, "plates": 21, "chapters": 12 } }
```
`era` is set at bake config (human), defaulted from a guess the admin UI proposes (author dates via Gutendex + title). It feeds transforms.

**structure.json** — `{ "chapters": [ { "index": 1, "title": "I", "page_ids": ["0001","0002",…] } ] }`

**pages/NNNN.json**
```json
{ "id": "0007", "seq": 7, "chapter": 1,
  "text": "…final immutable text…", "word_count": 641,
  "ledger": { …scene-update output verbatim… } }
```

**cast.json**
```json
{ "characters": [ { "slug": "time-traveller", "name": "the Time Traveller",
    "aliases": ["the Traveller"], "mention_pages": ["0001","0002",…],
    "major": true,
    "visual_description": "…", "one_line": "…", "tags": ["…"],
    "portrait": "images/portraits/time-traveller.png" | null,
    "edited_by_human": false } ] }
```

**selection.json**
```json
{ "preset": "classic",
  "params": { "min_gap": 2, "max_gap": 6, "salience_floor": 0.55,
              "chapter_open": true, "scene_boundary": true },
  "plates": [ { "page_id": "0007", "reason": "chapter_open|scene_boundary|fill|manual",
                "salience": 0.82,
                "status": "selected|approved|rendered|retired",
                "added_in_revision": 1 } ] }
```

**prompts/NNNN.json**
```json
{ "page_id": "0007",
  "derived": { …illustration-prompt output verbatim… },
  "edited_prompt": null,
  "final_subject_prompt": "…(edited_prompt ?? derived.prompt)…",
  "wrapped_prompt": "…style-wrapped string actually sent to imagegen…",
  "negative_prompt": "…style.negative + derived.avoid…",
  "render": { "at": "…", "params_echo": {…}, "attempts": 1 } }
```

**manifest.json**
```json
{ "book_id": "pg-35", "revision": 3, "bundle_version": 1,
  "files": [ { "path": "pages/0001.json", "sha256": "…", "bytes": 4312 }, … ],
  "reader_required": ["meta.json","structure.json","pages/*","cast.json",
                      "selection.json","images/web/**","images/thumbs/**"],
  "total_bytes_reader": 83411234 }
```
Full-res `images/plates/*.png` are archival; readers download only `reader_required` by default.

### 4.4 Immutability & revisions (ADR-0002)

- After first publish: `meta` core identity fields, `structure.json`, and every `pages/*.json` **text** are frozen. (`pages/*.ledger` is also frozen — it's provenance.)
- Revisions are **additive**: a re-selection (density knob re-turned) or plate re-render may add files and update `selection.json`/`prompts/*`/`meta.stats`/`manifest.json`, bumping `revision`. Plates are never deleted; deselected plates get `status: "retired"` and their files remain.
- Client delta sync = manifest diff by path+sha256: download new/changed, never delete text, may prune `retired` plate images locally.
- Publish-time guard: if `library/{id}` exists, every existing `pages/*.json` must be byte-identical to the new bake's, else publish refuses (this is what makes annotation anchors permanently safe).

### 4.5 Sync-layer files (server-side, outside bundles; schemas in `shared/schemas/`)

**annotations/{user}/{book}.json**
```json
{ "book_id": "pg-35", "user_id": "kris",
  "annotations": [ { "id": "uuid", "type": "highlight|note|bookmark",
      "page_id": "0007", "anchor": { "start": 120, "end": 188 },
      "text": "note body (note only)", "color": "yellow|blue|green|pink",
      "created": "…", "modified": "…", "deleted": false } ] }
```
Anchors are **character offsets into the page's immutable `text`** (UTF-16 code-unit offsets, because that is what JS `Selection` gives you — document this in the schema description; the server never interprets anchors). `bookmark` uses `anchor: {"start": 0, "end": 0}` (page-level). Deletion is a tombstone (`deleted: true`, `modified` bumped) so LWW works.

**positions/{user}/{book}.json**
```json
{ "furthest": { "page_seq": 42, "char": 310, "modified": "…" },
  "current":  { "page_seq": 17, "char": 0,  "modified": "…", "device": "pixel8" } }
```

## 5. Ingestion

**Adapter interface** (`ingest/base.py`): `def load(source: SourceSpec) -> RawBook` where `RawBook = {title?, author?, language?, chapters: [ {title?, paragraphs: [str]} ]}`. A paragraph is a display unit; **verse stanzas are paragraphs with internal `\n` preserved**.

### 5.1 `gutenberg` adapter (network — the only one)
- Catalog/search via Gutendex (`https://gutendex.com/books?search=…`); admin UI search calls this through the server (readers never touch it).
- Fetch: prefer the Gutendex `formats["text/plain; charset=utf-8"]` link; fall back to any `text/plain` variant. Store the raw file in `work/{id}/source/` (provenance + offline re-bake).
- Strip PG boilerplate: content between the `*** START OF …PROJECT GUTENBERG EBOOK…***` and `*** END OF …***` marker lines (regex tolerant of `THE`/`THIS` variants and casing). If markers absent, take the whole file and set a `boilerplate_unstripped` warning on the job.
- Chapter detection heuristics, applied in order on stripped text, first that yields ≥2 chapters wins:
  1. Lines matching `^(CHAPTER|Chapter|BOOK|PART|CANTO)\s+([IVXLC]+|\d+)\b.*$`
  2. Standalone Roman-numeral lines `^[IVXLC]+\.?$`
  3. Standalone ALL-CAPS lines ≤ 60 chars surrounded by blank lines
  If all fail → single chapter titled by the book, and the job carries a `chapters_undetected` warning; **the admin UI's chapter editor (S9) lets a human insert/adjust chapter breaks before phase P1 runs** — chapter breaks happen pre-bake, so fixing them is cheap.
- Metadata (title/author/language) from Gutendex; overridable in bake config.

### 5.2 `markdown` adapter
- `#`/`##` headings → chapter breaks (first heading level that appears ≥2 times is the chapter level); heading text → chapter title; content split on blank lines → paragraphs; other markdown syntax passed through as plain text v1 (no rendering).
- Front-matter (`---` YAML) honored for `title/author/language/era` if present.

### 5.3 Direct file / paste
- Admin UI accepts an uploaded `.txt`/`.md` or pasted text → routed to the corresponding adapter with `source.kind: "user"`. This also makes Gutendex outages a non-event (grab the file anywhere, sideload it).

### 5.4 Deferred adapters (registered names, no cycles): `epub`, `chronicle-transcript` (the delighter — Chronicle sessions arrive with structured entities, so P1/P2 are skipped and cast.json is seeded directly; design when scheduled).

## 6. Pagination

Pure function `paginate(RawBook, params) -> [Page]`, golden-tested.

Params (fixed v1): `target=550`, `min=400`, `max=850` words.

Algorithm:
1. Chapters never share a page; each chapter starts page fresh.
2. Greedily append whole paragraphs while `word_count < target`; stop before exceeding `max`.
3. If stopping would leave the page `< min` and the next paragraph would exceed `max`: split that paragraph on sentence boundaries (regex `(?<=[.!?…])\s+`, tolerant) at the point nearest `target`. Paragraph-splitting is the only time a paragraph breaks.
4. A chapter's final page may be `< min` (unavoidable); never merge across chapters.
5. Verse paragraphs (contain `\n`) are never sentence-split; they move whole, even if that makes a page slightly over `max` (cap: 1.25×max, else split on stanza-internal line boundaries).
6. Page text = paragraphs joined by `\n\n`, exactly as stored — **byte-stable forever** (anchors!). No trailing whitespace, NFC-normalized, `\n` line endings.
7. Output per page: `text`, `word_count`, `chapter`, `seq`, zero-padded `id`.

Determinism requirement: same input + params ⇒ byte-identical pages. Golden tests lock this.

## 7. Bake pipeline

A bake is a **job** (persisted at `jobs/{job_id}.json`) that advances a book through phases. Everything below is orchestrated by the server's single-worker async job runner (§11.2).

### 7.1 Phase table

| Phase | Name | Runs on | Unit | Uses | Checkpoint artifact (in `work/{id}/`) |
|---|---|---|---|---|---|
| P0 | ingest+paginate | i5 CPU | book | adapter, paginator | `raw_book.json`, `pages/*.json` (text only), `structure.json` |
| P1 | cast mentions | GPU-LLM | page (parallel-safe, but runner is serial anyway) | `cast-mentions` | `mentions/{page_id}.json` |
| P2 | cast reduce + canonicalize | i5 CPU then GPU-LLM | character | reducer + `cast-canonicalize` | `cast.json` |
| P3 | scene ledger + scoring | GPU-LLM | page, **strictly sequential** | `scene-update` | `ledgers/{page_id}.json` |
| P4 | selection | i5 CPU | book (instant) | selection engine (§8) | `selection.json` |
| P5 | prompt derivation | GPU-LLM | selected page | `illustration-prompt` | `prompts/{page_id}.json` (status draft) |
| P6 | **REVIEW GATE** | human | book | admin UI (§11.3) | approval flag in job + edited files |
| P7 | render | GPU-SDXL | plate / portrait / cover | imagegen client (§10) | `images/**` |
| P8 | publish | i5 CPU | book | manifest builder | `library/{id}/**` |

### 7.2 P2 reducer (deterministic, CPU — spelled out because it's fiddly)

Input: all `mentions/*.json`. Steps:
1. Normalize labels: trim, collapse whitespace, strip possessive `'s`, casefold **for matching only** (display keeps original casing of the most frequent variant).
2. Union-find grouping: two labels merge if (a) exact normalized match, (b) one appears in another mention's `aliases`, or (c) one is a single-token subset of the other's tokens minus articles/honorifics (`the, a, mr, mrs, miss, dr, sir, lady, lord`) — e.g., "Weena" ⊂ "little Weena". Never merge two labels that co-occur in the same page's `present`/mention list as distinct entries (guard against merging "Eloi" into "Weena").
3. Per group: `name` = most frequent full label; `aliases` = the rest; `mention_pages` = union; `descriptors` = concatenated, order-preserving, exact-dup-deduped, capped at 40 (keep earliest).
4. `is_person` majority vote; non-person groups kept in cast.json but `major` only if human promotes.
5. `major` = person groups mentioned on ≥3 pages **or** top-6 by page count, whichever is larger set.
6. `cast-canonicalize` called for majors only; minors get `visual_description: null` (renderable prompts just won't name them with detail).
7. Slugs: kebab-case of name, de-articled, uniquified with `-2` suffixes.
Unit-tested against hand-built mention fixtures including the Weena/Eloi guard case.

### 7.3 Job state machine

States: `created → ingested → mentions_running → mentions_done → cast_done → ledger_running → ledger_done → selected → prompts_running → prompts_draft → in_review → approved → rendering → published`. Cross-cutting: `waiting_gpu` (any GPU phase, on 503-class from either GPU service; retried each runner tick, default every 120s), `paused` (human), `failed` (human-attention; only from bug-class errors per TTS DESIGN §8).

Resume rules: every GPU phase, on (re)entry, lists its units, skips units whose checkpoint artifact exists and parses, processes the rest. P3 additionally requires contiguity: it resumes from the first page lacking a ledger and threads from the previous page's stored ledger. Killing the server at any moment therefore loses at most one in-flight unit.

Unit-level failure (422 after the TTS-side retry): retry the unit up to 3 more times with 10s/60s/300s backoff; then record `failed_units` on the job, continue the phase, and surface prominently in review (a page with no ledger inherits the previous page's ledger with `carry_notes += " [ledger gap]"`; a failed prompt page simply can't be approved until regenerated or hand-written).

### 7.4 GPU sequencing & wake (system invariant #5, #6)

- Before entering P7: call TTS `POST /v1/models/unload {}` and require success (else `waiting_gpu`).
- The runner is single-worker: LLM phases and render phases can never interleave across jobs either.
- At job start and on every `waiting_gpu` retry: send Wake-on-LAN (`wakeonlan {GPU_MAC}` via subprocess; `GPU_MAC`, `GPU_WOL_ENABLED` in config), then poll TTS `/health` (or imagegen health for P7) with 15s timeout before proceeding.

## 8. Selection engine (P4)

Pure function: `select(pages: [PageScore], structure, params) -> [PlateChoice]` where `PageScore = {seq, page_id, chapter, scene_changed, visual_salience}` — **numbers and booleans only; no text enters selection** (spoiler invariant: lookahead over scores is allowed, content lookahead is not).

**Presets:**

| Preset | min_gap | max_gap | salience_floor | chapter_open | scene_boundary |
|---|---|---|---|---|---|
| `lavish` | 1 | 3 | 0.40 | yes | yes |
| `classic` (default) | 2 | 6 | 0.55 | yes | yes |
| `sparse` | 4 | 12 | 0.85 | yes | no |

**Algorithm (deterministic, documented in code):**
1. Mandatory marks: first page of each chapter (`chapter_open`); pages with `scene_changed=true` (`scene_boundary`, if enabled).
2. Enforce `min_gap` over marks in seq order: when two marks are closer than `min_gap`, keep the one with higher precedence (chapter_open > scene_boundary), tie-break higher salience, tie-break earlier seq.
3. Fill: scan seq order; whenever the gap since the last kept mark exceeds `max_gap`, choose the page with max `visual_salience ≥ salience_floor` in the window `(last+1 … last+max_gap)`; if none clears the floor, skip (gaps may exceed max_gap rather than force a weak plate).
4. Tiny-work degradation: if total pages < 8 → exactly {page 1} ∪ {argmax salience} (dedup); presets ignored.
5. Output reasons per plate (`chapter_open|scene_boundary|fill`).

**Illustration richness (`images_per_scene`).** A book-level dial (≥1, default 1) for *how densely
to illustrate*. It scales the effective preset tighter — `min_gap ← round(min_gap/n)`,
`max_gap ← max(round(max_gap/n), 2·min_gap)` (`effective_params`) — so a higher value makes the same
even-spacing engine select proportionally more **distinct** pages, one picture each, spread across the
whole book. `n=1` leaves the preset unchanged (byte-identical to a single-picture bake); the effective
params are what get written to `selection.json`. (Superseded ADR-0016: earlier this knob split one page
into `n` clustered pictures, which piled illustrations at a scene's opening page — retired.)

**Re-selection** (density knob re-turned later): run fresh, then diff against existing `selection.json`: new choices are added (`status: selected`, `added_in_revision: current+1`); previously rendered plates not re-chosen become `retired` (files kept — additive invariant); previously rendered plates re-chosen stay `rendered` (no re-render). Only `selected` plates flow to P5/P7.

Manual overrides in review (§11.3) add/remove with `reason: "manual"`; manual removals of never-rendered plates simply delete the entry.

## 9. Style system

`styles.json` (server data dir, seeded at S1; schema in shared/):
```json
{ "styles": [ {
    "id": "engraving", "name": "Victorian Engraving",
    "consistency_friendly": true,
    "prefix": "19th-century steel engraving book illustration, fine crosshatching, monochrome ink, dramatic light, ",
    "suffix": ", intricate linework, aged paper tone, high detail",
    "negative": "photo, color photograph, modern, text, watermark, signature, blurry",
    "portrait_prefix": "19th-century engraved portrait plate, bust composition, fine crosshatching, monochrome ink, ",
    "params": { "steps": null, "cfg": null } } ] }
```
Seed four v1 styles: `engraving`, `woodcut` (bold carved lines, high contrast, limited palette), `watercolor` (loose washes, soft edges, muted palette), `gouache-storybook` (flat shapes, warm palette, mid-century children's-book feel). First three are `consistency_friendly: true`; gouache is `false`. The admin style picker sorts friendly-first and shows a one-line warning on unfriendly styles ("identity drift more visible in this style"). Chronicle's 13 styles can be **copied** in later (copy, don't couple — different negative-prompt needs).

`params` overrides imagegen defaults when non-null; v1 leaves them null.

## 10. Rendering (P7)

**imagegen client:** `render/imagegen.py` defines `ImagegenClient` protocol: `async def txt2img(prompt, negative, width, height, seed=None) -> bytes(png)` + `async def health() -> bool`. `FakeImagegen` (returns a deterministic placeholder PNG with the prompt hash burned in — Pillow-generated) serves all tests and lets R-track and S-track run without the GPU. **S10 opens by reading imagegen-service's actual repo/API and implementing the real client against it**; capabilities assumed (all proven by Chronicle): txt2img, negative prompt, size, style-neutral (style rides in the prompt). If imagegen exposes style/LoRA selection natively, the real client MAY use it, mapped from `styles.json` — decide in S10's ADR against the real API, don't guess now.

**Assembly:** `wrapped = style.prefix + final_subject_prompt + style.suffix`; `negative = style.negative + ", " + join(derived.avoid)`. Store both in `prompts/{page}.json` (provenance).

**Sizes:**

| Asset | Render | Web derivative | Thumb |
|---|---|---|---|
| Plate | 832×1216 PNG | ≤1080w WebP q80 | 320w WebP |
| Cover | 832×1216 | same | same |
| Portrait | 1024×1024 | ≤768w | 320w |

**Cover:** rendered from a dedicated prompt assembled CPU-side (no LLM): `"{style.prefix}frontispiece for the book '{title}' by {author}: {best_visual_beat of the max-salience page in chapter 1}{style.suffix}"` — reviewable/editable in the gate like any plate (it appears as a pseudo-plate `page_id: "cover"`).

**Portraits (optional, `portraits_enabled`):** one per major character with a canonical description: prompt = `style.portrait_prefix + one_line + ", " + visual_description condensed to ≤60 words` (simple truncation on sentence boundary). Also review-gated (pseudo-plates `portrait:{slug}`).

**Derivatives:** Pillow: WebP resize, LANCZOS, quality 80. Idempotent (skip if exists with matching source hash recorded in a sidecar `.src.sha256`).

**Per-plate regen:** review UI can re-fire a single plate (new seed) pre- or post-publish; post-publish regens write a new file `…/0007-r2.png` and update `prompts/0007.json.render` + selection entry — additive.

## 11. Server app (i5)

FastAPI, uv, Python 3.12 (house pattern). Serves three API groups + two static apps (admin-ui build, reader PWA build). Port: `SCRIPTORIUM_PORT` default **8720**.

### 11.1 Endpoint table

| Method+Path | Purpose | Notes |
|---|---|---|
| `GET /health` | server up, TTS reachable?, imagegen reachable?, jobs summary | never 500s |
| **Admin** (`/api/admin/*`) | | |
| `GET /api/admin/gutendex?q=` | proxy Gutendex search | network; admin only |
| `POST /api/admin/books` | create book from source spec `{kind: gutenberg\|text\|markdown, …}` + bake config `{style_id, density_preset, era?, portraits_enabled, title?/author? overrides}` → creates job, runs P0 | |
| `GET /api/admin/books` / `GET /api/admin/books/{id}` | list/detail incl. job state, warnings, failed_units | |
| `PUT /api/admin/books/{id}/chapters` | chapter-break editor (pre-P1 only) → re-runs P0 pagination | 409 if past P0 |
| `POST /api/admin/jobs/{id}/(start\|pause\|resume)` | job control | start advances to next phase per state machine |
| `GET /api/admin/books/{id}/review` | full review payload: selection + prompts + cast + pseudo-plates + failed units | |
| `PUT /api/admin/books/{id}/review/prompt/{page_id}` | `{edited_prompt}` | pre-approval only for new text; post-publish allowed for regen flow |
| `PUT /api/admin/books/{id}/review/selection` | add/remove manual plates | |
| `PUT /api/admin/books/{id}/review/cast/{slug}` | edit visual_description/one_line → sets `edited_by_human` | |
| `POST /api/admin/books/{id}/approve` | locks shot list → `approved` | refuses if any selected plate lacks a prompt |
| `POST /api/admin/books/{id}/plates/{page_id}/regen` | single-plate re-render (new seed) | |
| `POST /api/admin/books/{id}/reselect` | `{density_preset}` → §8 re-selection → back through P5(new only)→P6→P7 | |
| **Library** (`/api/library/*`, readers) | | |
| `GET /api/library` | published books: id, title, author, cover thumb URL, revision, total_bytes_reader | |
| `GET /api/library/{id}/manifest` | manifest.json | |
| `GET /api/library/{id}/files/{path}` | bundle file serving | path-traversal-guarded (resolve + prefix check), ETag = sha256 |
| **Sync** (`/api/sync/*`) | | |
| `GET /api/users` | profiles for the picker | |
| `GET/PUT /api/sync/annotations/{user}/{book}` | PUT body = client's full doc; server merges (§12), writes backup, returns merged doc | |
| `GET/PUT /api/sync/positions/{user}/{book}` | merge per §12 | |

Auth: none v1 (ADR-0005, profile-picker trust). Admin group is *additionally* protected by bind: admin-ui is only linked from the LAN; if that ever feels thin, add the TTS-style optional shared-secret — noted in ADR, not built.

### 11.2 Job runner

Single asyncio worker started with the app: loop { pick oldest runnable job → advance one *phase-or-unit-batch* → persist job json after every unit }. `waiting_gpu` jobs re-checked every `RUNNER_TICK_S=120` (with WoL per §7.4). No Celery, no Redis — jobs are JSON files, the queue is a directory scan, and there is exactly one worker (which also enforces GPU exclusivity for free). Server restart: runner rescans `jobs/`, resumes per §7.3.

### 11.3 Admin UI (`admin-ui/`, served at `/admin`)

Functional-first, desktop-oriented. Screens: **Books** (list + New Book wizard: source → Gutendex search or paste/upload → metadata/era → style picker with thumbnails per style (pre-rendered static samples committed to the repo) → density → create); **Book detail** (phase progress, warnings, failed units, chapter editor while available, job controls); **Review** (the heart: table of plates — thumb-less pre-render — page id, reason, salience, beat sentence, prompt (inline-editable), include-toggle; cast side panel with editable descriptions; cover + portrait pseudo-plates; Approve button with confirmation showing plate count); **Post-render review** (same table with rendered thumbs, per-plate Regen). Keep it boring and dense; this is a workbench.

## 12. Sync design

Server-authoritative merge; clients send full docs, receive merged full docs (documents are small — a heavy reader's book might hold a few hundred annotations).

**Annotations merge:** union by `id`; per id keep the copy with greater `modified` (ISO string compare is safe — always UTC, always second-or-finer precision from `Date.toISOString()`); tombstones (`deleted: true`) participate identically and are retained ≥180 days before compaction (compaction deferred, documented). After merge: write `sync/annotations-backups/{user}/{book}/{now}.json`, prune to newest 20.

**Positions merge:** `furthest` = max by tuple `(page_seq, char)` regardless of timestamps (furthest-read-wins); `current` = greater `modified` (LWW). Reader UX: "Continue" opens `current`; if `furthest > current`, show a subtle "jump to furthest" chip.

**Conflict examples (tests encode these):** same annotation edited on two offline devices → later `modified` wins wholesale; deleted on one, recolored on the other → later `modified` wins (deletion can lose — acceptable, documented); positions: phone read to p50, desktop to p30 later in time → `furthest` p50, `current` p30.

**Progress visibility:** household-visible v1 — `GET /api/sync/positions/{user}/{book}` is not restricted by requesting profile (config flag `PROGRESS_PRIVATE=false` reserved; not implemented v1). Reader may show "Amy is on ch. 4" on shared books' shelf cards.

## 13. Reader client

One React+TS app; platform differences isolated behind two small interfaces in `shell/`:
`Storage` (`readFile/writeFile/exists/delete/list`, binary+text) and `Platform` (`persistHint()`, `share()?`).
Implementations: **CapacitorStorage** (`@capacitor/filesystem`, Directory.Data) for Android/iOS; **OpfsStorage** (Origin-Private File System) for the desktop PWA, calling `navigator.storage.persist()` on first checkout and surfacing the result in Settings ("storage protected: yes/no"). ADR-0006 records: if desktop eviction is ever observed in practice, the fallback is wrapping the same app in Electron/Tauri — interfaces make that a shell swap.

**Checkout flow:** shelf shows library (server reachable) with Download; download = fetch manifest → fetch `reader_required` files not already present (sha256-verify each; resumable by construction) → write `manifest.local.json` → book becomes **Resident**. Revision bump on server → shelf badge → delta = manifest diff. Remove = delete local files, keep annotations (they're synced anyway; confirm dialog says so).

**Reading surface (ADR-0004):** v1 renders **one logical page as a vertically scrolled unit**, with page-turn navigation between logical pages (swipe/tap-zones on touch, ←/→ + buttons on desktop). Rationale: true screen-pagination (measure/reflow/hyphenate) is a deep rabbit hole orthogonal to everything else; scroll-within-page works identically on both form factors, keeps plate placement trivial, and keeps anchors simple. Revisit post-v1 only with evidence it hurts. Plate placement: top of its logical page, full-width, tap → zoomable lightbox (pinch on touch). Chapter-open pages show the chapter title header.

**Annotations UX:** text selection → floating bar: Highlight (4 colors), Note (highlight + text sheet), Copy. Bookmark = toolbar toggle per page. Annotations list screen per book (filter by type/color, tap → jump). Anchors = UTF-16 offsets into page text via `Selection`/`Range` against a text-rendering that is exactly `text` split on `\n\n` into `<p>`s (offset math accounts for paragraph joins — implement once, unit-test hard with multi-paragraph fixtures; this is the fiddliest client code, budget accordingly in R2).

**Search:** MiniSearch index over `{page_id, text}` built at checkout completion (novel-scale ≈ seconds), persisted via `toJSON` to storage, loaded lazily. Results → page + highlight-flash of the match. (FTS5/wa-sqlite rejected for v1: heavier cross-platform surface for no capability we need at this scale — ADR-0006.)

**Dramatis personae:** auto page before chapter 1 listing major cast (portrait thumb if enabled, name, one_line). Tappable from a toolbar "Cast" button anywhere — *shows only characters whose `mention_pages` include any page ≤ furthest-read* (causality invariant applies to the reader too; cheap filter, big spoiler win).

**Settings:** font size (5 steps), theme (light/sepia/dark), typeface (Literata default / Inter) — both fonts **vendored** in the repo with their OFL license files (ADR-0003); profile switcher; sync status + manual sync button; storage status.

**Offline rules:** all server calls live in `sync/` + `shelf/` modules only; every one is wrapped in reachability guard (2s health ping, cached 60s); failures are silent-with-indicator (cloud-off icon). Reading path performs zero fetches. A grep-able rule: `fetch(`/HTTP client usage outside those two modules fails review (add an ESLint `no-restricted-imports`/custom rule in R1 to enforce mechanically).

**Sync triggers:** app foreground, book close, every 10 min while reachable, manual.

## 14. Multi-user

`users.json`: `[{id, name, color}]`, managed in admin UI (v1: hand-edit file is acceptable; admin CRUD is a stretch goal in S12). Reader first-run: profile picker (avatar circles); switchable in Settings; per-device single active profile. All local annotation/position files namespaced `{user}/{book}` mirroring the server layout, so sync is a straight per-user exchange.

## 15. Invariants → ADR seeds

Cycle S1 creates these ADRs; the one-liners below are the normative statements (context/consequences from this doc):

- **ADR-0001** Monorepo `server/ reader/ admin-ui/ shared/`; schemas in `shared/` are the single source of truth; TS types generated from them (`json-schema-to-typescript`) in the reader build.
- **ADR-0002** Bundle immutability + additive revisions + publish integrity guard (§4.4 verbatim).
- **ADR-0003** Zero-online read path: no CDN assets ever; fonts vendored; model/service versions pinned in `meta.bake`; ESLint-enforced network-module boundary (§13).
- **ADR-0004** Reader reflow: scroll-within-logical-page v1 (§13 rationale).
- **ADR-0005** Auth: profile-picker LAN trust; no passwords; optional shared-secret reserved, unbuilt.
- **ADR-0006** Client storage: Capacitor FS + OPFS behind `Storage`; MiniSearch over SQLite; Electron/Tauri as recorded fallback.
- **ADR-0007** The i5 data dir is canonical and must have an off-box backup before M1 closes.
- **ADR-0008** Causality: generation sees only pages ≤ N; selection sees scores only; reader cast page filters by furthest-read (§8, §13).
- **ADR-0009** GPU sequencing: single job worker; explicit TTS unload before render; WoL on wait (§7.4).
- **ADR-0010** Fallback is time: TTS/imagegen error taxonomy consumed as pause/retry signals per TTS DESIGN §8; no paid providers in this repo.

## 16. Milestone M1 — First Full Bake (acceptance)

Book: **The Time Machine** (PG #35). Config: `classic`, `engraving`, portraits on, era "1890s England".

Checklist:
- [ ] Ingest via Gutendex through admin UI; chapters detected (12 + epilogue-ish; verify against text) or fixed in chapter editor.
- [ ] P1–P5 complete unattended; `failed_units` = 0 (or each explained).
- [ ] Review gate: human edits ≥1 prompt and toggles ≥1 plate (exercise the paths), approves.
- [ ] Render completes; plate count sane for classic (expect ~15–25 for ~110–120 pages); cover + ≥3 portraits exist.
- [ ] Publish; bundle validates against every schema; manifest verifies (`tools/verify_bundle.py` — built in S10).
- [ ] Checkout on one Android device and one desktop PWA; **then disable Wi-Fi/stop the server**: open book, read, highlight, note, bookmark, search, view cast page — all functional.
- [ ] Re-enable network: annotations from both devices merge; positions show furthest-wins behavior.
- [ ] Kill-tests during a second bake (any GPU phase, mid-phase `systemctl restart`): job resumes losing ≤1 unit.
- [ ] Blind-read 10 plates against their pages: no spoilers, characters recognizable across plates (log verdicts in CYCLE-LOG).
- [ ] ADR-0007 backup exists.

## 17. Deferred register (named, unscheduled)

epub adapter · chronicle-transcript adapter · TTS narration · Navidrome chapter-mood playlists · shared/cross-user highlights · internal link annotations · true typographic pagination · iOS build polish (Android ships first in R5; iOS after, same code) · IP-Adapter portrait conditioning in imagegen · annotation-tombstone compaction · admin shared-secret auth · `PROGRESS_PRIVATE` flag.
