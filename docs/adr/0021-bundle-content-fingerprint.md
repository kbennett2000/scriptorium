# ADR 0021: bundle content fingerprint — reader detects a re-made book

- **Status:** Accepted
- **Date:** 2026-08-08
- **Relates to:** [ADR-0002](0002-bundle-immutability.md) (immutability / delta-by-sha256),
  DESIGN §4.3–4.4, §13.

## Context

A reader that had checked out a book kept showing a **stale** copy after the book was deleted and
re-made server-side. Concretely: *The Brothers Karamazov* (`pg-28054`) was published, checked out,
then deleted and re-baked with the pipeline fixes. The reader never loaded the corrected bundle.

Root cause, two halves:
- **Server:** `revision` is derived only from the on-disk `library/{id}/meta.json`
  (`p8_publish.py`), which `purge_book` deletes. So a delete + re-make restarts `revision` at **1** —
  identical `(book_id, revision)` to the old bundle, different content.
- **Reader:** the checkout cache is keyed on `book_id` alone; residency (`checkout.ts bookState`) is a
  purely-local existence check that never reconciles against the server. Nothing re-downloads a book
  the reader thinks it owns. The hash-based reconciler `delta()` existed but had **no caller**.

The manifest carried only per-file `sha256` — no cheap single value to compare — and `revision` was
useless here because it collided.

## Decision

Add a **`content_fingerprint`** to the manifest: the SHA-256 of the sorted `path\0sha256` file list
(`_content_fingerprint` in `p8_publish.py`, added in `build_manifest`). It is a pure function of the
bundle's files, so it differs whenever any file's bytes differ — **even when `book_id` and
`revision` collide**. Additive metadata; it touches no page bytes.

The reader uses it to reconcile:
- `checkForUpdate(client, storage, bookId)` (new, in `checkout.ts`) does one small manifest GET and
  compares `server.content_fingerprint` to the stored local one. A local manifest predating the
  field has none, so any server fingerprint reads as "update available" (the safe direction).
- The Shelf calls it (online only) for each Resident book on load/Refresh, marks changed books
  **"Update available,"** and an **Update** action runs the previously-dead `delta()` to fetch only
  changed files by sha256 and prune removed ones.

## Why this does not weaken any invariant

- **Immutability / integrity guard untouched.** The fingerprint is derived, additive metadata; no
  published page bytes change, and the integrity guard (`p8_publish.py _integrity_guard`) is
  unaffected. Byte-stability of paginator output is unrelated and unchanged.
- **Zero-online read path preserved.** All reconciliation lives in `shelf/` (already the reader's
  network boundary, ESLint-fenced). The reading surface gains no network call; the check runs only on
  explicit shelf load / Refresh / Update.
- **Revision semantics unchanged.** We do **not** try to make `revision` survive deletes (that would
  need a tombstone the purge design deliberately avoids). Revision still counts republishes of a
  living bundle; the fingerprint is the identity that survives a delete + re-make.

## Consequences

- `content_fingerprint` is a required manifest field (schema + regenerated TS types). Every new
  publish emits it; bundles published before this change simply lack it until re-baked — and a reader
  holding a fingerprint-less local manifest treats the next server fingerprint as an update, which is
  correct.
- Because `meta.json` embeds `revision` + a completed-at timestamp, the fingerprint changes on **every**
  republish, not only on content change. That is acceptable: an unnecessary "Update available" costs
  one cheap `delta()` (mostly just `meta.json`), and never shows stale content.
- Recovery for an already-stale book without server support is unchanged: Remove + Download.
