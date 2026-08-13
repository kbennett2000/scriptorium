# ADR 0029: deferred portrait generation + upload at the review gate

- **Status:** Accepted
- **Date:** 2026-08-12
- **Relates to:** [ADR-0025](0025-portrait-review-gate.md) (the optional portrait gate this extends),
  [ADR-0023](0023-character-consistency-portrait-reference.md) (portraits seed pages via IP-Adapter),
  [ADR-0028](0028-single-subject-portraits-and-identity-only-conditioning.md) (portrait assembly),
  DESIGN §7.3 (state machine), §10 (render), §11.1 (review gate).

## Context

ADR-0025 added the optional portrait gate: when the per-book `portrait_review` flag is set, the
bakery renders **every** portrait first, then pauses at `portraits_review` so the owner can
regenerate the ones they dislike. But the owner still meets the gate with the machine's *default*
faces already chosen — the generation happened before they had any say. The owner wants to author
each character deliberately: land on the same review screen but with **no portraits drawn yet**, and
for each character either (a) accept the stock description and click **Generate** to get the default,
(b) edit the prompt/description then generate, or (c) **upload their own image**. Each portrait then
seeds every page that character appears on (ADR-0023), so getting it right up front matters.

Most of the machinery already existed: `regen_plate` / `edit_prompt` / `edit_cast` already operate at
`portraits_review` and already render a portrait **cold** from its P5 prompt file (P5 writes
`prompts/portrait-{slug}.json` regardless of any render flag). What was missing: not drawing the
portraits up front, telling the UI which portraits exist yet, an image-upload path, and a rule for
what happens when the owner approves with some portraits still blank.

## Decision

**1. Curated gate starts blank.** `PortraitRender._plate_ids_for` returns `[]` when
`bake_config.portrait_review` is set (p7_render.py), so the phase renders no portraits and lands at
`portraits_review` empty. It keeps its leading `__unload__` unit, so the TTS-unload + imagegen-health
GPU handoff is unchanged.

**2. Blanks fill from defaults at page-render time.** `Render._plate_ids_for` now lists portraits
**first, then cover + pages** (previously it excluded portraits). Because `unit_done` is
existence-based, any portrait already on disk (generated or uploaded) is skipped and only the
*blanks* draw — from each portrait's current (possibly edited) prompt. Portraits-first ordering
guarantees a page's reference PNG exists before the page draws.

**3. Approval is not blocked by blanks.** `approve_portraits` is unchanged (a plain
`portraits_review → rendering` transition). The screen **warns** when blanks remain — they will be
drawn from the stock description, i.e. exactly the no-gate default — and offers a **"Generate all
remaining"** shortcut that fills only blanks (never overrides an already-made portrait).

**4. Upload endpoint** (review_api.py) — `POST /books/{id}/portraits/{slug}/upload` (multipart),
gated to `portraits_review` and to characters that have a portrait prompt. The image is
**center-cropped to the 1024×1024 portrait square** (fills the frame, trims the overflow — the right
default for a headshot), written as the archival PNG + web/thumb derivatives (the same three files a
render produces via `make_derivatives`), and the prompt's `render` provenance is stamped
`source='upload'`. `python-multipart` is added (the repo's first multipart handler).

**5. Schema.** `prompt.schema.json` `render` gains an optional `source` enum (`render` | `upload`);
absent means `render`. Types regenerated via `just gen-types`.

**UI** (admin-ui): the `PortraitReview` screen reads a new `portrait_rendered: {page_id: bool}` field
from `get_review` and shows, per blank card, a dashed placeholder with **Generate** and **Upload
image** (reusing `regenPlate` for generate); a **Generate all remaining (N)** batch button and the
blank warning sit by Approve. The wizard sub-option gains a one-line hint.

## Why this keeps the invariants

- **Byte-stability / immutability:** the off-flag path is untouched — `PortraitRender` still batch-
  renders, `Render` lists portraits first but existence-based `unit_done` skips every already-drawn
  one, so the golden P0→P8 bundle output is byte-identical. Generated portraits use the same
  deterministic prompt/seed as before. Uploads and regenerated portraits overwrite only the
  **work-tree** PNG pre-publish (already blessed by ADR-0025); no published bytes ever mutate, so the
  publish integrity guard is untouched.
- **Causality / review gate:** the stop is still after approval and before page render; it adds
  authoring affordances, never a bypass. Pages still seed from the portraits present at approval.
- **GPU sequencing:** `PortraitRender` keeps its leading `__unload__` even when it draws nothing;
  on-demand generation goes through `render_plate` after TTS is already unloaded.

## Scope / limits

- Upload normalization is center-crop only (no in-UI crop/reposition); a very wide/tall upload loses
  its edges. Uploaded images are not validated for "single face" — the owner owns that choice.
- `source='upload'` is provenance only; a later Generate/Regenerate reverts a portrait to a render.
- The flag still lives in `bake_config`, not published `meta` — a bake-time control, not a bundle
  property.
