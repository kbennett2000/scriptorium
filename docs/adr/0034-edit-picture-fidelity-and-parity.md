# ADR 0034: edit-picture fidelity to the active reader + full imagegen-harness parity

- **Status:** Accepted
- **Date:** 2026-08-13
- **Relates to:** ADR-0033 (per-plate picture edits), ADR-0013 (imagegen style passthrough),
  ADR-0023/0026/0028 (reference conditioning), ADR-0030 (selectable base model),
  ADR-0031 (custom/no-style looks), DESIGN §8, §10.

## Context

The first cut of the post-publish picture editor (ADR-0033) had two defects that made a replaced
plate look nothing like the book:

1. **It ignored the reader in view.** A style set (ADR-0014) re-illustrates a book under a different
   style *and* checkpoint. But `edits.generate_candidate` always regenerated from the **base book** —
   its `meta.bake.models.imagegen` checkpoint, with the bare subject prompt and **no style** — so
   editing a plate while reading the "Comic Book" set re-rendered it in the base book's photoreal
   look (`epicrealismXL` + a `custom` 35mm style), not comic.
2. **It stripped the style entirely** even for a base-book edit: it passed `final_subject_prompt`
   (the *style-neutral* subject, no prefix/suffix) and no LoRA preset, so a styled book reverted to
   the raw checkpoint output.

It also exposed almost none of what the imagegen dev harness (`POST /generate`) offers: no negative
prompt, style, model, quality, or character-reference controls.

## Decision

**The edit reproduces the render of the reader the user is actually viewing, then exposes the full
harness control set as overrides.**

- **Reader-aware by default.** The context/candidate endpoints take a `set_id` (the reader's active
  set; `"default"`/absent ⇒ base book). The active reader's `{style_id, custom_style, model}` is
  resolved from that set's `set.json`, else from the book's `meta.json`. The candidate render then
  **reuses the exact art-set assembly** (`scriptorium.artsets.phase`): `resolve_style` →
  `wrap_prompt` (style prefix/suffix + LoRA `imagegen_style`) → the reader's checkpoint →
  `portrait_reference` cast conditioning. The img2img **starting image** is the *set's* rendered
  plate when a set is active (falling back to the base plate), so the repaint begins from what the
  reader sees. Default change-amount dropped to 0.45 so an edit stays on-model.
- **Full harness parity as overrides.** The editor surfaces Negative prompt, Style (styles catalog),
  Model (installed checkpoints, via `ImagegenClient.models()`), Quality (`fast`/`standard`/`high`,
  a new `txt2img(quality=…)` client param forwarded only when set — byte-stable otherwise), Seed,
  Change amount, and a **character-likeness** section: keep the cast portrait (default) and/or an
  uploaded reference photo with an optional IP-Adapter strength. Each override defaults to the active
  reader's value, so the form opens already set to match — and every knob is adjustable.
- **The edit is self-describing.** `edits.json` records the `style_id`/`custom_style`/`model`/
  `negative`/`quality`/`reference_strength` a replacement was made with (new optional `artset-edits`
  fields), so re-opening the editor resumes from them.

Delivery is unchanged from ADR-0033: writes stay in the private `artsets/{user}/{book}/edits/`
overlay; the reader checks it out via `artsetCheckout` and shows the replacement offline. All network
stays in the reader's `shelf/` boundary — the style/model picker lists come **through the bakery**
(`plate_context`), never a direct reader→imagegen call — and `GpuUnavailable → 503`, never a fallback.

## Consequences

- Editing a plate on any reader (base book or a style set) now yields an image in that reader's own
  look, on-model, instead of reverting to the base checkpoint's raw style — the core bug fixed.
- The editor is a faithful in-app imagegen harness; a reader can retune style/model/quality/likeness
  per plate without a whole-book re-roll.
- Uploaded reference photos are accepted as base64 in the candidate body (decoded server-side); the
  cast portrait remains the default reference so characters stay consistent with zero effort.
- Still scoped to page plates (cover/portrait editing remains a follow-up). `source_revision` still
  records the book revision the edit derived from, so a later re-publish is detectable, not
  auto-invalidated.
