// The platform-abstraction seam (DESIGN §13). All persistence goes through `Storage`; the reading
// path never touches the network. Two implementations back it — `OpfsStorage` (desktop PWA) and
// `CapacitorStorage` (Android/iOS, wired in R5) — plus `MemoryStorage` for tests. Swapping the
// desktop backend for Electron/Tauri later is a shell swap, nothing else (ADR-0006).
//
// Paths are POSIX-style, `/`-separated, relative to a single app root (e.g.
// `books/usr-…/pages/0001.json`). Binary and text are distinct calls so no impl has to guess an
// encoding.

export interface Storage {
  readText(path: string): Promise<string>;
  readBytes(path: string): Promise<Uint8Array>;
  writeText(path: string, data: string): Promise<void>;
  writeBytes(path: string, data: Uint8Array): Promise<void>;
  exists(path: string): Promise<boolean>;
  /** Delete a single file, or — when `path` names a directory — the whole subtree. No-op if absent. */
  delete(path: string): Promise<void>;
  /** All file paths at or under `prefix` (a directory prefix), in no guaranteed order. */
  list(prefix: string): Promise<string[]>;
}

/** Split a storage path into non-empty segments, rejecting anything that could escape the root. */
export function splitPath(path: string): string[] {
  const parts = path.split("/").filter((p) => p.length > 0);
  if (parts.some((p) => p === "." || p === "..")) {
    throw new Error(`unsafe storage path: ${path}`);
  }
  return parts;
}
