# ADR 0036: book-wide user negative prompt at creation time

- **Status:** Accepted
- **Date:** 2026-08-13
- **Relates to:** ADR-0026 (hardened negative + era anchor), ADR-0031 (custom/no-style looks),
  ADR-0034 (edit-picture per-plate negative), ADR-0014 (per-user art sets), DESIGN §10.

## Context

The imagegen service accepts a `negativePrompt`, and the post-publish picture editor (ADR-0034)
already lets a reader steer one plate's negative. But **new book creation exposed no user negative
at all**: the bake wizard sent none, and every plate's negative was assembled entirely by machine in
`wrap_prompt` — `style.negative` + the global anti-deformity/anachronism guard (`_GLOBAL_NEGATIVE`,
ADR-0026) + the per-scene `derived.avoid`. An owner who wanted "no text/watermarks across this whole
book" had no way to say so up front; the only lever was editing plates one at a time after publish.

## Decision

**A book carries one optional owner-typed negative prompt, set at bake time, applied to every
plate.**

- **Append, not replace.** The owner's negative is layered on top of the machine-derived terms via
  the existing `_dedupe_terms` — it is appended **last**, so `style.negative` and the
  `_GLOBAL_NEGATIVE` anatomy/period guardrails keep priority and any overlap is dropped. The field
  means "*also* avoid these", and the safety net that stops extra limbs / modern dress stays on for
  the whole book. (This differs from the per-plate editor, which *replaces* the negative for one
  fine-tuned image — a book-wide replace would silently disarm the guardrails.)
- **Threaded through the one assembly point.** `wrap_prompt(style, plate_id, doc, era,
  user_negative=None)` gains the parameter and folds it into both branches (page plates and the
  cover/portrait pseudo-plates). `None`/`""` is a no-op → existing books and recorded fixtures render
  byte-identically. P7 passes `job.bake_config.get("negative")`.
- **Persisted so sets inherit it.** The negative is written into the published bundle's `meta.json`
  (schema-validated; optional/absent on pre-ADR-0036 bundles). A style-set re-render — whose job
  `bake_config` carries only `style_id` — reads it back via `_book_negative(cfg, job)`, mirroring how
  `_era` already recovers the period anchor for sets (ADR-0026). So a Comic/Cyberpunk re-illustration
  honors the same "also avoid these" terms as the base book.
- **No imagegen protocol change.** The real service already forwards `negativePrompt` unconditionally;
  the owner's terms flow through the already-built `negative` string. `_digest` is intentionally left
  unchanged (negative was never folded in — same as ADR-0034's edit path) so existing byte-stable
  fake-render fixtures don't churn; tests assert on the recorded negative string / `txt2img` args,
  never on image bytes (CLAUDE.md).

## Consequences

- The bake wizard gains a "Negative prompt (optional)" field (`NewBookWizard.tsx`), sent as
  `bake.negative` (`BakeBody.negative`, `CreateBookBody.bake.negative`). Blank → omitted → prior
  behavior exactly.
- The negative is pinned in `meta.json`, so `-rN` regens and art-set re-rolls reproduce it.
- Still one book-wide string, not per-scene — a scene that needs something *extra* excluded is still
  the picture editor's job. Delivery, the review gate, the zero-online read path, and
  `GpuUnavailable → waiting_gpu` are all untouched: this only enriches the pre-render prompt
  assembly.
