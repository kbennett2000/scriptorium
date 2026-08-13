# ADR 0031: "No style" and free-text custom-prompt looks

- **Status:** Accepted
- **Date:** 2026-08-13
- **Relates to:** [ADR-0013](0013-style-lora.md) (style = prompt + LoRA), [ADR-0014](0014-art-sets.md)
  (art sets), [ADR-0030](0030-selectable-base-model.md) (selectable base model). DESIGN §9 (styles),
  §10 (render).

## Context

The style picker (new book, and new art set) only offered the fixed `styles.json` catalog. The owner
wanted two more options: **"No style"** — send the subject prompt to the model with no artistic
prefix/suffix/LoRA — and a **free-text custom look** — type e.g. "photorealistic" and have it drive
every picture. Both are the same axis as `style_id`; the difference is one is a fixed entry and one is
owner-supplied text.

## Decision

- **"No style" is a real catalog entry** (`styles.json` id `none`) with empty `prefix`/`suffix`/
  `portrait_prefix`/`negative` and a null LoRA. The schema already allows empty strings, so this
  needs **no code** — it resolves, publishes, and re-rolls like any style, and the subject prompt
  reaches the model raw (only the anti-garbage global negative — bad anatomy, duplicates — still
  applies, since that is quality, not style).
- **Custom is a sentinel `style_id: "custom"`** (not a catalog entry) plus a `custom_style` free-text
  field. A new `resolve_style(bake_config)` synthesises a prompt-only style whose `prefix` is the
  text (`"photorealistic, "`), no LoRA; empty text ⇒ identical to "No style". Every place that
  materialised a style now calls `resolve_style(bake_config)` instead of `get_style(style_id)` —
  P5 (portrait/cover assembly + re-derive), P7 (`render_plate`), art-set `SetRender`, and the
  post-publish `-rN` regen.
- **Threaded like every other bake control:** `BakeBody.custom_style` and `CreateSetBody.custom_style`
  → `bake_config` → `resolve_style`. Art sets: a `style` set may pick custom; a `reroll` inherits the
  book's `style_id` **and** `custom_style` so it reproduces the look. The chosen text is pinned in
  `meta.custom_style` (and `set.json.custom_style`) so re-rolls and `-rN` regens reproduce it.
- **UI:** the admin wizard grows a "Custom…" tile that reveals a text input (and "No style" simply
  appears as a catalog tile); the reader's New-set panel grows an "Or describe your own look…" input
  with a "Make it" button (and lists "No style" as a normal style button).

## Why this keeps the invariants

- **Byte-stability:** existing catalog `style_id`s resolve through `resolve_style` → `get_style`
  unchanged; `custom_style` defaults to null and is folded into nothing. The offline golden bundle and
  every existing book render byte-identically.
- **Immutability:** `custom_style` is a bake-time control in `bake_config`; the only published surface
  is the additive, optional `meta.custom_style` provenance field (and `set.json`). No page bytes or
  existing plate files change; the integrity guard is untouched.
- **Reproducibility:** `-rN` regen reads the persisted job `bake_config`; art-set re-rolls read
  `meta`, so both reproduce a custom book's exact look.

## Scope / limits

- Custom is prompt-only — it never applies a LoRA (there is no LoRA for arbitrary text).
- No validation of the free text (it is a prompt fragment); an empty custom look degrades to "No
  style" rather than erroring.
- "No style" still keeps the global anti-garbage negative; a truly raw pass (no negative at all) is
  not offered.
