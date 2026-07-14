// The shelf's public surface: the library client, the checkout state machine, and `-rN` resolution.
// This module (with sync/, R3) is the reader's network boundary — the ESLint fence bans fetch/HTTP
// everywhere else (DESIGN §13).

export type { LibraryClient, LibraryEntry } from "./client";
export { ApiError, HttpLibraryClient } from "./client";
export type { BookState, CheckoutOptions, CheckoutProgress, DeltaResult } from "./checkout";
export { bookState, checkout, delta, remove, residentEntries, sha256Hex } from "./checkout";
export {
  matchesAny,
  resolveReaderFiles,
  resolvedTotalBytes,
  variantKey,
} from "./resolve";
export type { ManifestFile } from "./resolve";
