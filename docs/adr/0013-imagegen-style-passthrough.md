# ADR 0013: imagegen style passthrough — optional LoRA presets per style

- **Status:** Accepted
- **Date:** 2026-07-14
- **Supersedes (in part):** ADR-0011's "client is style-neutral" consequence.

## Context

ADR-0011 bound the imagegen-service API and decided the render client would be
**style-neutral** — style rides entirely in the prompt (`prefix`/`suffix`/`negative` from
`data/styles.json`), and the service's `style`/LoRA selection was left unused. At the time
Scriptorium shipped 4 prompt-only styles.

The product owner asked for **the same art styles his "Chronicle" app offers**. Probing the
live imagegen-service (`GET /styles`, `GET /health`) shows it exposes **12 LoRA-backed
presets** — *pixel art, oil painting, comic book, lego-style, pencil sketch, watercolour,
anime, storybook, 3d, cyberpunk, ukiyo-e, claymation* — where the distinctive look comes
from the **LoRA**, not from prompt words. `POST /generate` already accepts an optional
`style` field (ADR-0011 endpoint map); the client simply never sent it. Unknown/unlisted
`style` strings are rendered prompt-only by the service (safe fallback).

So the prompt-only approach can copy the style *names* but not the *look*. Delivering the
real look requires forwarding `style`.

## Decision

- **Extend the style catalog.** `data/styles.json` (schema `styles`) gains a required field
  `imagegen_style: string | null` — the imagegen preset name to forward (e.g.
  `"oil painting"`), or `null` for prompt-only styles. The 4 original styles keep
  `imagegen_style: null`; the 12 Chronicle presets are added with their exact engine names.
- **Make the client optionally style-aware.** `ImagegenClient.txt2img` /
  `RealImagegenClient.txt2img` gain `style: str | None = None`; when set, the client includes
  `"style"` in the `/generate` body. When `None` the body is **byte-identical** to the
  pre-0013 client, so nothing changes for prompt-only styles.
- **Thread it through render.** P7 `render_plate` already loads the full style dict; it passes
  `style["imagegen_style"]` into `render_to_spec` → `txt2img`. P8 post-publish regen looks up
  the book's style from `meta.style_id` and passes the same, so `-rN` re-renders stay
  consistent with the original.
- **Fake parity.** `FakeImagegen` accepts `style` and folds it into its digest **only when
  non-`None`**, so existing determinism / paginator round-trip fixtures (which pass no style)
  remain byte-stable, while distinct styles yield distinct placeholders.

## Consequences

- Books baked with a Chronicle style now render under that style's LoRA — the real look, not
  a prompt approximation. Prompt-only styles are unaffected.
- **Immutability preserved.** Already-published books (e.g. *The Time Machine* on `engraving`)
  map to `imagegen_style: null`, so their render requests are unchanged; their bundles are
  immutable on disk regardless.
- A typo in `imagegen_style` degrades silently to prompt-only (the service ignores unknown
  names). `tests/test_styles_catalog.py` guards every value against the known preset set.
- The service's `quality` tier and per-call sampler knobs remain unused (still no need).
- No API keys or secrets introduced (unchanged from ADR-0011).
