# ADR 0030: selectable base model (checkpoint) per book and per art set

- **Status:** Accepted
- **Date:** 2026-08-13
- **Relates to:** [ADR-0011](0011-imagegen-api.md) (imagegen client), [ADR-0013](0013-style-lora.md)
  (style = prompt + LoRA), [ADR-0014](0014-art-sets.md) (per-user art sets),
  [ADR-0023](0023-character-consistency-portrait-reference.md) (portraits seed pages),
  imagegen-service ADR-0004 (selectable-base-checkpoint). DESIGN §9 (styles), §10 (render).

## Context

Scriptorium's axiom is "style rides in the prompt/LoRA, not the model": a `styles.json` entry sets a
prompt prefix/suffix and an optional `imagegen_style` LoRA preset, all layered on **one** base SDXL
checkpoint that was a service-side global. The owner wanted to choose *which installed base model* a
book (or a new art set) renders with — the model is a different axis from style and materially
changes the look.

The imagegen-service already supports this end to end (its ADR-0004): `GET /health` returns the full
installed `checkpoints` list plus the effective default, and `POST /generate` accepts a per-request
`checkpoint` (precedence request > config > workflow default). Scriptorium simply never sent it.

## Decision

Add an optional **base model** as a first-class, book-wide axis that mirrors how `style_id` already
flows, defaulting to the service's own default (so every existing book is byte-identical).

- **Wire contract** (`render/imagegen.py`): `txt2img` gains `checkpoint: str | None`; `None` omits it
  (byte-identical request), a value sends `body["checkpoint"]`. `FakeImagegen` folds it into its
  digest so a different model yields a visibly different stand-in while `None` stays byte-stable. New
  `RealImagegenClient.models()` reads `/health` → `{models, default, reachable}` (best-effort).
- **List endpoint**: `GET /api/admin/models` proxies `models()` (never 500s). Served unauthenticated
  on the LAN like `/api/admin/styles`, so the reader's picker can read it too.
- **Bake**: `BakeBody.model` → stored in `bake_config` → read in `render_plate` and passed as
  `checkpoint`. Book-wide, because pages are IP-Adapter–conditioned on the portraits (ADR-0023) —
  one model per book keeps character consistency.
- **Art sets**: `CreateSetBody.model` → stored on `set.json` and the set job's `bake_config` → passed
  in `SetRender`. A `style` set may pick any installed model; a `reroll` with no explicit model
  defaults to the book's own pinned model so it reproduces the book's look with fresh seeds.
- **Provenance / immutability**: the chosen model overrides the service-reported tag in
  `meta.bake.models.imagegen` at publish, so post-publish `-rN` regens and art-set re-rolls (which
  re-derive from stored config) reproduce the exact model. `artset.model` is persisted (schema
  updated).
- **UI**: an optional "Base model (advanced)" picker in the admin New-Book wizard and an "Image
  engine" selector in the reader's New-set panel, both defaulting to "Automatic" and shown only when
  the service lists installed models.

Validation is deliberately light: the pickers only offer installed names, and an unknown checkpoint
fails cleanly at render (imagegen 503 → `waiting_gpu`). Create-book/create-set stay decoupled from a
live service probe so they work when imagegen is momentarily down.

## Why this keeps the invariants

- **Byte-stability:** `model=None` sends no `checkpoint` and folds nothing into the fake's digest, so
  the offline golden bundle and every existing book render byte-identically.
- **Immutability:** the model is a bake-time control in `bake_config`; the only published surface it
  touches is the `meta.bake.models.imagegen` provenance tag, pinned once at publish. No page bytes or
  existing plate files change.
- **Character consistency:** the model is book-wide (and a reroll inherits the book's model), so a
  book never mixes checkpoints between its portraits and the pages that condition on them.
- **Zero-online read path:** the reader's model list fetch lives in `shelf/` (the network-permitted
  fence), best-effort, and reading a resident set needs no model info at all.

## Scope / limits

- No per-plate or per-character model override (book-wide only, by design).
- No model *catalog* with friendly names/thumbnails — the picker shows raw `ckpt_name`s from the
  service. A curated catalog (à la `styles.json`) is a later refinement.
- LoRA-vs-checkpoint compatibility is not validated; a style's LoRA may not suit every base model.
