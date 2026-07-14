// The sync feature's public surface. This module (with shelf/) is the reader's network boundary — the
// ESLint fence bans fetch/HTTP everywhere else (DESIGN §13). Merge is a bit-for-bit port of the S12
// server merge, pinned to it by shared/test-vectors/sync-merge.json.

export type { SyncClient } from "./client";
export { HttpSyncClient, SyncApiError } from "./client";
export { mergeAnnotations, mergePositions, canonicalJson } from "./merge";
export { syncAllBooks, readSyncState, SYNC_EVENT } from "./engine";
export type { SyncOutcome, SyncState } from "./engine";
export { useSync } from "./useSync";
export type { SyncStatus } from "./useSync";
export { SyncStatusBadge } from "./SyncStatus";
