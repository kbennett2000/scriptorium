// The shelf's public surface: the library client, the checkout state machine, and `-rN` resolution.
// This module (with sync/, R3) is the reader's network boundary — the ESLint fence bans fetch/HTTP
// everywhere else (DESIGN §13).

export type { LibraryClient, LibraryEntry } from "./client";
export { ApiError, HttpLibraryClient } from "./client";
export type { BookState, CheckoutOptions, CheckoutProgress, DeltaResult } from "./checkout";
export {
  bookState,
  checkForUpdate,
  checkout,
  delta,
  remove,
  residentEntries,
  sha256Hex,
} from "./checkout";
export type {
  ArtsetClient,
  ArtsetCheckoutOptions,
  ArtsetCheckoutProgress,
  SetState,
} from "./artsetCheckout";
export {
  artsetCheckout,
  HttpArtsetClient,
  removeSet,
  setState,
} from "./artsetCheckout";
export type { ArtsetApi, CreateSetBody, ModelOptions, StyleOption } from "./artsetApi";
export { HttpArtsetApi } from "./artsetApi";
export type {
  Candidate,
  EditContext,
  GenerateBody,
  VideoBody,
  VideoCandidate,
  VideoInfo,
} from "./editPicture";
export {
  candidateUrl,
  commitEdit,
  commitVideo,
  fetchEditContext,
  generateCandidate,
  generateVideoCandidate,
  videoCandidateUrl,
} from "./editPicture";
export {
  matchesAny,
  resolveReaderFiles,
  resolvedTotalBytes,
  variantKey,
} from "./resolve";
export type { ManifestFile } from "./resolve";
