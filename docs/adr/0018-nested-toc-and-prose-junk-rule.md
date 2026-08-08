# ADR 0018: prune dense/nested tables of contents with a prose-based junk rule

- **Status:** Accepted
- **Date:** 2026-08-08
- **Refines:** [ADR-0017](0017-frontmatter-toc-pruning.md) (front-matter/TOC pruning) and DESIGN §5.1
  chapter detection (the `gutenberg` adapter, shared by `textfile`).

## Context

The product owner baked *The Brothers Karamazov* (Project Gutenberg #28054) and it came out
unreadable: the real Chapter 1 didn't start until ~page 14, chapters were scrambled and out of
order (109 of them), and the first ~13 pages were near-empty (word_count 1–6) — each just a line
like `Book II. An Unfortunate Gathering` / `Epilogue` / `Footnotes` — every one of which drew a
nonsense illustration.

ADR-0017 fixed the simpler *A Tale of Two Cities* case but not this one. *Karamazov* breaks four of
ADR-0017's assumptions at once:

1. **Nested structure** — Part > Book > Chapter (two divider tiers), not one.
2. **Per-book numeral reset** — chapter numbering restarts (`Chapter I`, `II`, …) inside *each*
   Book, so a flat detected list carries repeating numerals.
3. **Vocabulary gap** — `Epilogue` / `Footnotes` are outside the `BOOK|PART|CANTO|VOLUME` divider
   vocabulary.
4. **Dense contents list** — TOC entries sit on consecutive lines with no blank separators, so
   `_section_headings` (which requires a blank-line bracket) never recognizes the TOC `Book …`
   lines; they fall through and get **swallowed as a one-line "body"** of the preceding contents
   entry. ADR-0017's `_prune_headings` kept any chapter with *any* paragraph, so those near-empty
   entries survived → the ~13 leaked pages.

Downstream, the near-empty page defeated both later guards: the P3 ledger safety net only
neutralized *fully empty* text, and P4 selection *force-picks every chapter opener* regardless of
salience — so each leaked chapter's page was illustrated.

## Decision

Stay in the **flat** chapter model (no Part>Book>Chapter data-model/schema/paginator/reader change —
that is a large blast radius against byte-stability/immutability for zero reader-visible gain; the
reader consumes a flat chapter list + a title string). Fix at ingest, plus one conservative
safety-net. All primary edits are in `server/src/scriptorium/ingest/base.py`.

- **Prose-based junk rule (the core).** A segmented chapter is *contents junk* iff it contains
  **zero non-heading prose** — after dropping blank lines and every heading-shaped line
  (`_is_headingish`: `_H1`/`_H2`/`_SECTION`/`_SECTION_WORD` or the ALL-CAPS-short H3 shape), no text
  remains (`_prose_word_count == 0`). This replaces ADR-0017's "has any paragraph" gate in
  `_prune_headings`. It needs **no magic word-count constant** and, crucially, cannot drop a
  genuinely short real chapter: a one-sentence chapter still has prose > 0 (verified against the
  real *Karamazov* page "Ivan was called to give evidence.").
- **Divider keywords in Title case.** `_H1` now matches `Book`/`Part`/`Canto` in Title case as well
  as ALL-CAPS (the numeral stays UPPER-Roman/digit to avoid catching a lowercase prose line), so a
  dense-TOC `Book II. …` registers as a boundary and its contents entries segment cleanly to
  prose-free (droppable) chapters.
- **Stacked Part/Book labels.** `_prune_headings` holds a prose-free `BOOK`/`PART`/`CANTO` heading
  as a *pending* label and **stacks** Part+Book, folding them into the section's first real chapter
  (e.g. `"PART I — Book I. The History Of A Family — Chapter I."`). Satisfies the owner's requirement
  that Part/Book titles are kept as headings, never a blank illustrated page.
- **`_SECTION_WORD` is recognition-only.** `Epilogue`/`Prologue`/`Footnotes`/… count as
  heading-shaped so a TOC entry that swallows them is prose-free and pruned — but they are **not**
  chapter boundaries. Making them boundaries would re-segment existing books that end in an Epilogue
  (pg35 *The Time Machine*) and drift their byte-stable pagination; a body Epilogue therefore folds
  into its preceding chapter (no junk page either way).
- **Safety net (`p3_ledger`).** The empty-page guard is broadened from *fully empty* to *≤3 words*
  (`_NEUTRAL_LEDGER_MAX_WORDS`): a stray divider/contents line that ever survived ingest gets a
  neutral ledger (salience 0, empty beat, no model call) and can never be illustrated. Threshold is
  kept far below a real one-sentence page. Byte-safe (only affects which new-bake pages call the
  model). Selection is left untouched (ADR-0008's text-free `PageScore`); once ingest removes the
  junk chapter, no junk opener exists to force-pick.

## Consequences

- **Byte-stability preserved.** The paginator, schemas, and published bundles are untouched; the
  pg35 pagination golden is unchanged (the `_SECTION_WORD`-as-boundary temptation was explicitly
  rejected for exactly this reason). Only *new* bakes' ingest changes; the owner re-makes #28054 to
  benefit.
- **On the real #28054:** 96 chapters (was 109 scrambled), real Chapter 1 leads (669 words), zero
  near-empty front pages, Part/Book titles stacked onto each section's first chapter.
- **No-op for the common case.** Books without a printed contents list and without Part dividers
  (pg35, pg_markers, allcaps, the ADR-0017 pg_toc) are unaffected: every chapter has prose, no
  divider/structural lines, so pruning changes nothing.
- **Known limitation.** A body `Epilogue`/`Footnotes` label folds into the previous chapter rather
  than heading its own (the numeral-bearing epilogue chapters, e.g. Karamazov's `Chapter I–III`,
  are still detected normally). Accepted to protect pg35 byte-stability; revisit only with a real
  nested-structure model.
