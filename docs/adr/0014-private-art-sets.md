# ADR 0014: private, multiple picture "sets" per book

- **Status:** Accepted
- **Date:** 2026-07-14
- **Relates to:** ADR-0002 (bundle immutability), ADR-0005 (LAN trust / no auth),
  ADR-0009 (GPU handoff), ADR-0013 (imagegen style passthrough), DESIGN §8.

## Context

Every book ships **one** set of illustrations, shared by all readers and frozen inside the
immutable published bundle (`library/{book_id}/`). Image bytes only ever reach a device by
checking out that shared bundle. The product owner wants the opposite for art: **each person can
have several picture "sets" per book** — make a new one in a different art style (or a re-roll of
the same style), switch between them, and delete them — all **private to that person**. The book's
*words* must stay locked (annotation anchors and byte-stable pagination depend on it); only the
*pictures* become personal and swappable.

This is a dimension the data model never had: per-person, mutable, create/delete-able image
collections. The render engine, however, is already fully style-parameterized (ADR-0013), so the
missing pieces are a **per-person container**, a **trigger** to generate one, and (later cycles) a
**private offline delivery** path.

## Decision

**Sets are images only.** Which pages get illustrated, and where, lives in the book's shared
`selection.json` and is identical for every set. A set therefore carries **no layout** — only image
files at the same plate ids. The synthetic `default` set is the shipped bundle art (no bytes of its
own); every profile starts there.

**Storage is outside the immutable bundle.** A personal set lives at
`artsets/{user}/{book}/{set_id}/` (new `cfg.artsets_dir`) with `set.json` (schema `artset`),
`manifest.json` (reuses the `manifest` schema), per-picture provenance, and its `images/…`.
`set_id = "set-" + secrets.token_hex(6)` — hex-only after `set-`, so it can never collide with the
`-rN` revision-variant suffix the reader's resolver recognises.

**Generation reuses the render *functions*, on the same single worker.** A create call writes
`set.json` (`status="generating"`) and enqueues a job whose id is `{book}#{set_id}` — distinct from
the book's own `jobs/{book}.json`, so `job.book_id` is shared but the record is separate. A new
`SetRender` phase runs it as a self-contained side lifecycle `set_rendering → set_done`. It reuses
the pure functions `wrap_prompt` / `_asset_spec` / `render_to_spec` and P5's `assemble_cover` /
`assemble_portrait` with the **set dir as the explicit output root** (it must *not* call
`render_plate`, which hard-codes `job.book_id` into `work/{book}` and would collide with the book).
Page-plate prompts are the book's already-approved, style-neutral prompts, re-wrapped in the set's
style at render; cover/portrait are re-assembled with the set's style. The seed folds `set_id`
(`sha256(book, set, plate)`), so a re-roll differs.

**A distinct terminal, wired explicitly.** `set_rendering` is a GPU state (parks on `waiting_gpu`,
unloads TTS first via the reused `__unload__` unit). It is kept **off** the book `_CHAIN` and wired
by hand in `_build_transitions` with `→ set_done` (terminal) and `→ failed` edges; the GPU pass adds
the `waiting_gpu` resume edge. Reusing the book's `published` terminal was rejected — it would
conflate set jobs with published books in `/health` counts and any state UI, and both `→failed` and
`→waiting_gpu` edges are mandatory or the runner's handlers raise inside their own `except` and kill
the worker loop.

**The create action is the review-gate approval.** The book-bake review gate ("no render before
human approval, no bypass") is left entirely intact. A personal set authors **no new AI text** — page
prompts are the approved published prompts; cover/portrait are deterministic template assembly over
the approved cast and the fixed style catalog — so there is nothing new to review, and the user's
explicit "create this set" request *is* the human approval for that specific GPU work. No separate
approve step, and no inline/off-runner render (unlike `regen_published_plate`).

## Consequences

- **Immutability / byte-stability preserved.** Sets never write under `library/{book}`; the publish
  integrity guard and frozen `pages/*.json` / `structure.json` are untouched. Delete is an
  `rmtree` of the set subtree plus its job file — it cannot affect the book or any other user.
- **Causality / no-spoilers preserved.** A set re-illustrates the same already-published pages from
  the same page-local prompts; the selection engine stays text-free.
- **GPU exclusivity preserved.** One worker, one phase per tick; TTS unloads before render;
  `GpuUnavailable → waiting_gpu`, never a paid fallback.
- **Privacy = LAN trust (ADR-0005), not auth.** "Private" means each profile has its own
  `{user}`-namespaced path, exactly as annotations do. There is no login; a technical peer on the
  same network could still reach another profile's path. True cryptographic privacy is a separate,
  larger project, explicitly out of scope.
- The composite `#` job id is **server-internal only** — it is disk-safe but a URL-fragment
  delimiter; routes carry `user`/`book`/`set_id` separately and compose the id server-side.
- **Delivered in phases:** Phase 1 (schemas + reader "Pictures" menu showing Default), Phase 2
  (server-side create/generate/delete), and Phase 3 (private offline download) are done; reader
  multi-set switching (the picker wiring + image-source swap) follows in Phase 4.

## Phase 3 — private offline delivery

A set's images reach a device the same way a book's do, but from a per-account path. Two read-only
serving endpoints mirror `library/api.py` exactly — `GET /api/artsets/{user}/{book}/{set_id}/manifest`
and `…/files/{path}`, with `ETag = sha256` (from the manifest), `If-None-Match` → 304, the
`{file_path:path}` converter, and the same `.resolve()` + `is_relative_to` traversal guard rooted at
`cfg.artsets_dir`. The synthetic `default` set has no bytes of its own and is excluded by the
`set-[0-9a-f]{12}` guard — Default art is served from the resident book bundle (`/api/library/…`), never
here. The set manifest is the one `p8_publish.build_manifest` already wrote, so it validates against
`manifest.schema.json` unchanged; no new schema.

On the device, `reader/src/shelf/artsetCheckout.ts` (a sibling of `checkout.ts`) downloads a set into
`artsets/{user}/{book}/{set_id}/` — **outside** `books/{id}/`, so the shelf's Remove-book and bundle
immutability are both untouched. It reuses `sha256Hex` and `resolveReaderFiles` verbatim and follows the
checkout contract: skip-if-already-good, verify-and-retry each file, and write `manifest.local.json`
**last** (the resumable Resident marker). It lives in `shelf/` because that (with `sync/`) is the reader's
only sanctioned network boundary (ESLint-enforced). Orphan-set pruning on book- or profile-removal is
deferred to Phase 5; `removeSet` handles the explicit per-set case today.
