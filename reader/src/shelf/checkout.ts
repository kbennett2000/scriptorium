import type { Manifest } from "@scriptorium/shared";

import { buildAndPersistIndexFromStorage } from "../search";
import type { Storage } from "../shell";
import type { Platform } from "../shell/platform";
import type { LibraryClient } from "./client";
import { resolveReaderFiles } from "./resolve";

// The checkout state machine (DESIGN §13, §4.4). A checkout downloads a bundle's resolved
// reader-required files (highest `-rN` per plate), sha256-verifies each, and — only once every file
// is present and correct — writes manifest.local.json, at which point the book is Resident. Because
// each file is verified and skipped-if-already-good, checkout is resumable by construction: an
// interrupted or corrupt download leaves the book Incomplete, and re-running fetches only what's
// missing or wrong. Delta on a server revision bump is the same walk against the new manifest.
//
// Storage layout: books/{id}/… holds the bundle verbatim; books/{id}/manifest.local.json is the
// Resident marker. Annotations live outside books/, so Remove keeps them.

const MAX_ATTEMPTS = 3;

export type BookState = "available" | "resident" | "incomplete";

export interface CheckoutProgress {
  file: string;
  done: number;
  total: number;
}

export interface CheckoutOptions {
  onProgress?: (p: CheckoutProgress) => void;
  platform?: Platform;
}

function bookRoot(bookId: string): string {
  return `books/${bookId}`;
}

function filePath(bookId: string, rel: string): string {
  return `${bookRoot(bookId)}/${rel}`;
}

function localManifestPath(bookId: string): string {
  return `${bookRoot(bookId)}/manifest.local.json`;
}

/** Lowercase hex SHA-256 of `bytes` (Web Crypto). Matches the manifest's per-file digest / ETag. */
export async function sha256Hex(bytes: Uint8Array): Promise<string> {
  // Copy into a fresh ArrayBuffer so the WebCrypto BufferSource type is satisfied regardless of the
  // input's backing buffer (Uint8Array is generic over ArrayBufferLike in TS 5.9+).
  const buf = new ArrayBuffer(bytes.byteLength);
  new Uint8Array(buf).set(bytes);
  const digest = await crypto.subtle.digest("SHA-256", buf);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function readLocalManifest(storage: Storage, bookId: string): Promise<Manifest | null> {
  if (!(await storage.exists(localManifestPath(bookId)))) return null;
  return JSON.parse(await storage.readText(localManifestPath(bookId))) as Manifest;
}

/** Fetch one file, verifying sha256 and retrying ONLY this file on mismatch. Throws if it can't be
 *  verified within MAX_ATTEMPTS (leaving the book Incomplete). */
async function fetchVerifyWrite(
  client: LibraryClient,
  storage: Storage,
  bookId: string,
  entry: { path: string; sha256: string },
): Promise<void> {
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    const bytes = await client.fetchFileBytes(bookId, entry.path);
    if ((await sha256Hex(bytes)) === entry.sha256) {
      await storage.writeBytes(filePath(bookId, entry.path), bytes);
      return;
    }
  }
  throw new Error(`checkout: ${entry.path} failed sha256 after ${MAX_ATTEMPTS} attempts`);
}

/**
 * Download `bookId` to Resident. Skips files already present with the correct hash (resumable);
 * writes manifest.local.json only after every resolved file verifies. On first checkout, asks the
 * platform to persist storage.
 */
export async function checkout(
  client: LibraryClient,
  storage: Storage,
  bookId: string,
  opts: CheckoutOptions = {},
): Promise<void> {
  const firstCheckout = !(await storage.exists(localManifestPath(bookId)));
  const manifest = await client.fetchManifest(bookId);
  const resolved = resolveReaderFiles(manifest);

  let done = 0;
  for (const entry of resolved) {
    const target = filePath(bookId, entry.path);
    let haveGood = false;
    if (await storage.exists(target)) {
      haveGood = (await sha256Hex(await storage.readBytes(target))) === entry.sha256;
    }
    if (!haveGood) {
      await fetchVerifyWrite(client, storage, bookId, entry);
    }
    done += 1;
    opts.onProgress?.({ file: entry.path, done, total: resolved.length });
  }

  await storage.writeText(localManifestPath(bookId), JSON.stringify(manifest));
  // Build the full-text search index now that every page is Resident (DESIGN §13). Best-effort: a
  // failure here must not fail the checkout — the reader rebuilds on first search (search#ensureIndex).
  await buildSearchIndexQuietly(storage, bookId);
  if (firstCheckout && opts.platform) {
    await opts.platform.persistHint();
  }
}

/** Build+persist the search index, swallowing errors (the reader rebuilds on first search if absent). */
async function buildSearchIndexQuietly(storage: Storage, bookId: string): Promise<void> {
  try {
    await buildAndPersistIndexFromStorage(storage, bookId);
  } catch {
    // Non-fatal: search#ensureIndex builds on first use.
  }
}

/** Derived Resident/Incomplete/Available state from local storage (no network). */
export async function bookState(storage: Storage, bookId: string): Promise<BookState> {
  const local = await readLocalManifest(storage, bookId);
  if (!local) {
    // No local manifest: either nothing downloaded (Available) or an interrupted checkout left
    // partial files behind (Incomplete — a resume will finish it).
    const present = await storage.list(bookRoot(bookId));
    return present.length > 0 ? "incomplete" : "available";
  }
  for (const entry of resolveReaderFiles(local)) {
    if (!(await storage.exists(filePath(bookId, entry.path)))) return "incomplete";
  }
  return "resident";
}

export interface DeltaResult {
  fetched: string[];
  pruned: string[];
}

/**
 * Bring a Resident book up to the server's current revision: fetch new/changed resolved files
 * (compared by path+sha256) and prune resolved files that the new manifest no longer includes
 * (e.g. a superseded `-rN` base). A book that isn't Resident is a full checkout instead.
 */
export async function delta(
  client: LibraryClient,
  storage: Storage,
  bookId: string,
): Promise<DeltaResult> {
  const local = await readLocalManifest(storage, bookId);
  if (!local) {
    await checkout(client, storage, bookId);
    return { fetched: ["<full checkout>"], pruned: [] };
  }
  const server = await client.fetchManifest(bookId);
  const serverResolved = resolveReaderFiles(server);
  const localBySha = new Map(resolveReaderFiles(local).map((e) => [e.path, e.sha256]));
  const serverPaths = new Set(serverResolved.map((e) => e.path));

  const fetched: string[] = [];
  for (const entry of serverResolved) {
    if (localBySha.get(entry.path) !== entry.sha256) {
      await fetchVerifyWrite(client, storage, bookId, entry);
      fetched.push(entry.path);
    }
  }

  const pruned: string[] = [];
  for (const path of localBySha.keys()) {
    if (!serverPaths.has(path)) {
      await storage.delete(filePath(bookId, path));
      pruned.push(path);
    }
  }

  await storage.writeText(localManifestPath(bookId), JSON.stringify(server));
  // Page text may have changed with the revision; rebuild the index (best-effort, as at checkout).
  if (fetched.length) await buildSearchIndexQuietly(storage, bookId);
  return { fetched, pruned };
}

/** Remove a book's local files. Annotations live outside books/{id}/, so they are kept (§13). */
export async function remove(storage: Storage, bookId: string): Promise<void> {
  await storage.delete(bookRoot(bookId));
}
