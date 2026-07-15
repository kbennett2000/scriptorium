import type { Manifest } from "@scriptorium/shared";

import type { Storage } from "../shell";
import { ApiError } from "./client";
import { sha256Hex } from "./checkout";
import { resolveReaderFiles } from "./resolve";

// Private picture-set download (ADR-0014 Phase 3), a sibling of checkout.ts. A personal "set" is a
// per-user re-illustration of an already-published book (same layout, different look). Its images are
// downloaded from the set-serving endpoints, sha256-verified per file, and stored OUTSIDE books/{id}
// at artsets/{user}/{book}/{setId}/… — so shelf Remove and bundle immutability are untouched. Like a
// book checkout it is resumable by construction: each file is skip-if-already-good, and
// manifest.local.json is written only once every resolved image verifies (the Resident marker).
//
// This module lives in shelf/ because it is the reader's network boundary (with sync/) — the ESLint
// fence bans fetch/HTTP everywhere else. The synthetic "default" set has no bytes here; Default art
// resolves from the resident book bundle (books/{id}/), never from this path.

const MAX_ATTEMPTS = 3;
const BASE = import.meta.env.VITE_SERVER_URL ?? "";

export type SetState = "available" | "resident" | "incomplete";

export interface ArtsetCheckoutProgress {
  file: string;
  done: number;
  total: number;
}

export interface ArtsetCheckoutOptions {
  onProgress?: (p: ArtsetCheckoutProgress) => void;
}

/** The set-serving client — mirrors HttpLibraryClient over /api/artsets/{user}/{book}/{setId}/… */
export interface ArtsetClient {
  fetchSetManifest(user: string, book: string, setId: string): Promise<Manifest>;
  fetchSetFileBytes(
    user: string,
    book: string,
    setId: string,
    filePath: string,
  ): Promise<Uint8Array>;
}

export class HttpArtsetClient implements ArtsetClient {
  async fetchSetManifest(user: string, book: string, setId: string): Promise<Manifest> {
    const resp = await fetch(`${BASE}${_base(user, book, setId)}/manifest`);
    if (!resp.ok) throw new ApiError(resp.status, `GET set manifest → ${resp.status}`);
    return (await resp.json()) as Manifest;
  }

  async fetchSetFileBytes(
    user: string,
    book: string,
    setId: string,
    filePath: string,
  ): Promise<Uint8Array> {
    // filePath keeps its slashes as path segments (matches HttpLibraryClient.fetchFileBytes).
    const resp = await fetch(`${BASE}${_base(user, book, setId)}/files/${filePath}`);
    if (!resp.ok) throw new ApiError(resp.status, `GET ${filePath} → ${resp.status}`);
    return new Uint8Array(await resp.arrayBuffer());
  }
}

function _base(user: string, book: string, setId: string): string {
  return `/api/artsets/${encodeURIComponent(user)}/${encodeURIComponent(book)}/${encodeURIComponent(setId)}`;
}

/** Device storage root for one person's set — OUTSIDE books/{id}/ so Remove-book never touches it. */
function setRoot(user: string, book: string, setId: string): string {
  return `artsets/${user}/${book}/${setId}`;
}

function filePath(user: string, book: string, setId: string, rel: string): string {
  return `${setRoot(user, book, setId)}/${rel}`;
}

function localManifestPath(user: string, book: string, setId: string): string {
  return `${setRoot(user, book, setId)}/manifest.local.json`;
}

async function readLocalManifest(
  storage: Storage,
  user: string,
  book: string,
  setId: string,
): Promise<Manifest | null> {
  const path = localManifestPath(user, book, setId);
  if (!(await storage.exists(path))) return null;
  return JSON.parse(await storage.readText(path)) as Manifest;
}

/** Fetch one image, verifying sha256 and retrying ONLY this file on mismatch. Throws if it can't be
 *  verified within MAX_ATTEMPTS (leaving the set Incomplete). */
async function fetchVerifyWrite(
  client: ArtsetClient,
  storage: Storage,
  user: string,
  book: string,
  setId: string,
  entry: { path: string; sha256: string },
): Promise<void> {
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    const bytes = await client.fetchSetFileBytes(user, book, setId, entry.path);
    if ((await sha256Hex(bytes)) === entry.sha256) {
      await storage.writeBytes(filePath(user, book, setId, entry.path), bytes);
      return;
    }
  }
  throw new Error(`artset checkout: ${entry.path} failed sha256 after ${MAX_ATTEMPTS} attempts`);
}

/**
 * Download a personal set to Resident. Skips images already present with the correct hash
 * (resumable); writes manifest.local.json only after every resolved image verifies.
 */
export async function artsetCheckout(
  client: ArtsetClient,
  storage: Storage,
  user: string,
  book: string,
  setId: string,
  opts: ArtsetCheckoutOptions = {},
): Promise<void> {
  const manifest = await client.fetchSetManifest(user, book, setId);
  const resolved = resolveReaderFiles(manifest);

  let done = 0;
  for (const entry of resolved) {
    const target = filePath(user, book, setId, entry.path);
    let haveGood = false;
    if (await storage.exists(target)) {
      haveGood = (await sha256Hex(await storage.readBytes(target))) === entry.sha256;
    }
    if (!haveGood) {
      await fetchVerifyWrite(client, storage, user, book, setId, entry);
    }
    done += 1;
    opts.onProgress?.({ file: entry.path, done, total: resolved.length });
  }

  await storage.writeText(
    localManifestPath(user, book, setId),
    JSON.stringify(manifest),
  );
}

/** Derived Resident/Incomplete/Available state from local storage (no network). */
export async function setState(
  storage: Storage,
  user: string,
  book: string,
  setId: string,
): Promise<SetState> {
  const local = await readLocalManifest(storage, user, book, setId);
  if (!local) {
    const present = await storage.list(setRoot(user, book, setId));
    return present.length > 0 ? "incomplete" : "available";
  }
  for (const entry of resolveReaderFiles(local)) {
    if (!(await storage.exists(filePath(user, book, setId, entry.path)))) return "incomplete";
  }
  return "resident";
}

/** Remove a personal set's local files (its subtree only). Leaves books/ and other sets untouched. */
export async function removeSet(
  storage: Storage,
  user: string,
  book: string,
  setId: string,
): Promise<void> {
  await storage.delete(setRoot(user, book, setId));
}
