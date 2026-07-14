import { Directory, Encoding, Filesystem } from "@capacitor/filesystem";

import type { Storage } from "./storage";
import { splitPath } from "./storage";

// Android/iOS `Storage` over `@capacitor/filesystem` (DESIGN §13, ADR-0006). Everything lives under
// `Directory.Data` — the app-private data dir, not user-visible and not evicted by the OS (see
// CapacitorPlatform.persistHint in ./platform). Semantics mirror OpfsStorage exactly so both back the
// same Storage contract (shell/storage-contract.ts): text is UTF-8, bytes are byte-exact via base64,
// `delete` is idempotent and subtree-capable, `list` walks a subtree, and `..`/`.` are rejected.
//
// Native `readFile`/`writeFile` speak strings: UTF-8 for text (Encoding.UTF8) and base64 for binary
// (no encoding). The base64 bridge below is byte-faithful for the full 0x00–0xFF range.

const DIR = Directory.Data;

/** Bytes → base64 (through a binary string; faithful for arbitrary bytes, not just UTF-8). */
function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  const CHUNK = 0x8000; // avoid arg-count limits on String.fromCharCode for large buffers
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode(...bytes.subarray(i, i + CHUNK));
  }
  return btoa(binary);
}

/** base64 → bytes (inverse of bytesToBase64). */
function base64ToBytes(b64: string): Uint8Array {
  const binary = atob(b64);
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) out[i] = binary.charCodeAt(i);
  return out;
}

/** Normalise a storage path to its safe, `/`-joined form, rejecting traversal. */
function normalize(path: string): string {
  const parts = splitPath(path);
  if (parts.length === 0) throw new Error("empty storage path");
  return parts.join("/");
}

export class CapacitorStorage implements Storage {
  async writeBytes(path: string, data: Uint8Array): Promise<void> {
    await Filesystem.writeFile({
      path: normalize(path),
      directory: DIR,
      data: bytesToBase64(data),
      recursive: true, // auto-create parent directories, like OPFS `{ create: true }`
    });
  }

  async writeText(path: string, data: string): Promise<void> {
    await Filesystem.writeFile({
      path: normalize(path),
      directory: DIR,
      data,
      encoding: Encoding.UTF8,
      recursive: true,
    });
  }

  async readBytes(path: string): Promise<Uint8Array> {
    const { data } = await Filesystem.readFile({ path: normalize(path), directory: DIR });
    // Native returns a base64 string; the web impl (unused here) returns a Blob.
    if (typeof data === "string") return base64ToBytes(data);
    return new Uint8Array(await data.arrayBuffer());
  }

  async readText(path: string): Promise<string> {
    const { data } = await Filesystem.readFile({
      path: normalize(path),
      directory: DIR,
      encoding: Encoding.UTF8,
    });
    return typeof data === "string" ? data : await data.text();
  }

  async exists(path: string): Promise<boolean> {
    try {
      await Filesystem.stat({ path: normalize(path), directory: DIR });
      return true;
    } catch {
      return false;
    }
  }

  async delete(path: string): Promise<void> {
    const p = normalize(path);
    try {
      await Filesystem.deleteFile({ path: p, directory: DIR });
      return;
    } catch {
      // Not a plain file (a directory, or already gone) — fall through to a recursive remove.
    }
    try {
      await Filesystem.rmdir({ path: p, directory: DIR, recursive: true });
    } catch {
      // Already absent — deletion is idempotent.
    }
  }

  async list(prefix: string): Promise<string[]> {
    const parts = splitPath(prefix);
    const root = parts.join("/");
    const out: string[] = [];
    await this.walk(root, out);
    return out;
  }

  /** Recursively collect every file path at or under `dir` (a `/`-joined prefix). */
  private async walk(dir: string, out: string[]): Promise<void> {
    let entries;
    try {
      entries = (await Filesystem.readdir({ path: dir, directory: DIR })).files;
    } catch {
      return; // prefix dir doesn't exist → nothing to list
    }
    for (const entry of entries) {
      const childPath = dir ? `${dir}/${entry.name}` : entry.name;
      if (entry.type === "directory") {
        await this.walk(childPath, out);
      } else {
        out.push(childPath);
      }
    }
  }
}
