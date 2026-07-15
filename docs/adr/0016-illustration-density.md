# ADR 0016: `images_per_scene` is a density dial, not a per-page multiplier

- **Status:** Accepted
- **Date:** 2026-07-15
- **Supersedes (in part):** the original "pictures per scene" per-page segmentation behaviour of
  DESIGN §8.

## Context

The product owner reported that books set to make **more than one picture per scene** placed all of
those pictures at the **start** of the scene — a few sentences apart — and then ran on for a long
stretch of text with no pictures at all. He wants illustrations **evenly spaced through the book**.

Root cause: the selection engine (`selection/engine.py`) already spreads illustration *pages* evenly
(chapter openers + scene boundaries + fill so no gap exceeds `max_gap`). But the `images_per_scene`
knob was then applied by `segment.expand_choices` / `even_segments`, which split **one ~550-word page**
into N slices and attached **all N pictures to that single page**. A page is only a few paragraphs, so
the pictures clustered at its top and the rest of the scene (later pages) got nothing. The code called
one page a "scene"; a real scene spans many pages — that mismatch was the defect.

## Decision

- **Re-interpret the knob as illustration *richness*.** `images_per_scene` (≥1, default 1) now
  tightens the effective preset spacing instead of splitting a page:
  `effective_params(params, n)` returns `min_gap ← max(1, round(min_gap/n))`,
  `max_gap ← max(round(max_gap/n), 2·min_gap)`, other fields unchanged. The engine then selects
  proportionally **more distinct pages**, one picture each, spread evenly across the whole book.
- **Applied at both selection call sites** — fresh bake (`p4_select.run_unit`) and the re-selection
  endpoint (`review_api.do_reselect`) — so re-turning the density knob reproduces P4's placement
  identically. Both pass `expand_choices(..., 1)` (the identity pass) and write the **effective**
  params into `selection.json`, so the file is self-describing.
- **`n == 1` is byte-identical.** The helper returns the preset unchanged for `n == 1`, so every
  existing single-picture bake — and every book that never set the knob — produces the exact same
  `selection.json` as before.
- **Invariant preserved.** `max_gap ≥ 2·min_gap` (the engine's fill windows depend on it) holds after
  scaling, so a tightened region is always fillable.
- **No schema or field rename.** `images_per_scene` stays in `meta.schema.json` (back-compat); only its
  meaning and the wizard copy ("How richly illustrated") change. `segment.py` / `even_segments` remain
  in place as an identity path (`n=1`) and to read already-published bundles that still contain compound
  `{page}-N` plates.

## Consequences

- New books with the dial > 1 get more illustrations, **evenly spaced**, with no opening-page pile-up
  and no long empty tail (subject to the preset's `salience_floor`, which may still leave a genuinely
  low-salience stretch unillustrated by design).
- **Immutability preserved.** Already-published bundles are untouched (their plates, including any old
  clustered compound plates, stay on disk and render as-is). Only *new* selections change.
- **Spoiler invariant preserved.** `effective_params` is pure integer math on the preset — no page text
  enters selection; `PageScore` is unchanged.
- The per-page multi-picture capability (compound plate ids, non-zero anchors from segmentation) is no
  longer produced for new work; the plate schema still permits it for back-compat.
