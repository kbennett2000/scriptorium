# ADR 0017: prune front-matter contents lines; keep section dividers as headings

- **Status:** Accepted
- **Date:** 2026-07-15
- **Refines:** DESIGN §5.1 chapter detection (the `gutenberg` adapter, shared by `textfile`).

## Context

The product owner baked *A Tale of Two Cities* (Project Gutenberg #98) and saw pages showing an
illustration with **no story text**, plus **nonsensical illustrations** (e.g. a floating book with
golden threads — a literal drawing of the section title "Book the Second — the Golden Thread").

Root cause, confirmed end-to-end:

1. **Ingest.** The heuristic-1 regex `^(CHAPTER|Chapter|BOOK|PART|CANTO)\s+([IVXLC]+|\d+)\b.*$`
   matches every line of the book's own **table of contents** (`CHAPTER IV     Congratulatory`, …).
   The whole contents list was detected as ~45 extra chapters, each with **no body**. The book's
   real section dividers (`Book the First--Recalled to Life`) use a *word* numeral ("First"), so the
   numbered heuristics never matched them — instead a divider line was silently absorbed as the tiny
   "body" of the preceding contents entry.
2. **Paginate.** An empty chapter deliberately emits exactly one empty page
   (`text=""`, `word_count=0`). ~42 empty chapters → 42 blank pages at the front of the book.
3. **Ledger.** The `scene-update` transform was called on the blank page text, so the model
   hallucinated a `best_visual_beat` and a non-zero `visual_salience`.
4. **Select / render / reader.** Selection has no emptiness filter (its `PageScore` is text-free by
   the spoiler invariant), so the hallucinated salience earned a plate; the reader rendered the plate
   above an empty text block → "a picture with no text".

## Decision

Two layers, both in ingest/bake — the spoiler-invariant selection engine and `PageScore` are **not**
touched.

- **Detect section dividers.** `_section_headings` collects short standalone lines matching
  `^(BOOK|PART|CANTO|VOLUME)` bracketed by blank lines (the H3 shape, so a prose sentence beginning
  "Part of…" is never caught). These are merged with the numbered headings before segmentation, so a
  divider becomes a real boundary instead of being swallowed as a fake body.
- **Prune the segmented chapters** (`_prune_headings`), walking in order:
  - a chapter **with body** is kept (prefixing any pending divider label into its title);
  - a **bodyless section divider** is held as a *pending* label — it survives only if the *next*
    chapter has a body (a real divider sits just before its section's first chapter; a
    contents-list divider is followed by more bodyless lines, which clear it);
  - any **other bodyless heading** (a contents entry / stray title) is dropped, clearing pending.
- **Safety net (`p3_ledger`).** Before the transform call, a page whose text is empty/whitespace is
  written a neutral ledger (`visual_salience: 0.0`, `best_visual_beat: ""`) and the model call is
  skipped. Any stray blank page (e.g. a genuinely empty user chapter) can then never be selected or
  illustrated, and no GPU/LLM work is wasted on it.

On the real #98 text this yields **45 chapters** (was 90), **0 blank pages** (was 42), ~135.5k words
preserved, and the three "Book the First/Second/Third" titles kept as headings on each section's
first chapter.

## Consequences

- **Immutability preserved.** Only the ingest of *new* bakes changes; already-published bundles are
  untouched. The published #98 must be re-made to benefit (the owner will do so).
- **No-op for the common case.** Books without a printed contents list and without Part dividers
  (all existing fixtures — pg35, pg_markers, allcaps) are unaffected: every heading has a body, no
  divider lines exist, so pruning changes nothing.
- **Best-effort part labels.** A Part title is preserved when the source repeats the divider in the
  body (Gutenberg classics typically do); if a book lists Parts only in its contents, the label may
  not survive — but no blank page is ever produced either way.
- The paginator's "empty chapter → one empty page" contract is unchanged; post-fix, real books simply
  never feed it an empty chapter.
