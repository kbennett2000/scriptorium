# ADR 0006: Client storage and search

- **Status:** Accepted
- **Date:** 2026-07-13

## Context

The reader owns whole books on-device after checkout and must read, search, and
annotate them entirely offline, on Android/iOS (Capacitor) and the desktop PWA.
Storage APIs and eviction behavior differ across those shells. See DESIGN §13.

## Decision

Platform differences hide behind two small interfaces in the reader's `shell/`:
`Storage` (read/write/exists/delete/list, binary + text) and `Platform`
(`persistHint`, optional `share`). Implementations: **CapacitorStorage**
(`@capacitor/filesystem`, Directory.Data) for Android/iOS; **OpfsStorage**
(Origin-Private File System) for the desktop PWA, which calls
`navigator.storage.persist()` on first checkout and surfaces the result in
Settings. Full-text search uses **MiniSearch** (index built at checkout, persisted
via `toJSON`, loaded lazily); FTS5/wa-sqlite is rejected for v1 as heavier
cross-platform surface for no capability we need at this scale.

## Consequences

- The reader app is one codebase; the desktop/mobile split is a shell swap.
- If desktop OPFS eviction is ever observed in practice, the recorded fallback is
  wrapping the same app in Electron/Tauri — again a shell swap behind `Storage`.
- Search is in-memory MiniSearch, sized for novel-scale corpora (index build in
  seconds).
