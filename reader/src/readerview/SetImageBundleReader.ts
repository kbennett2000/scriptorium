import type { Manifest } from "@scriptorium/shared";

import type { Storage } from "../shell";
import { resolveReaderFiles, variantKey } from "../shelf/resolve";
import type { BundleReader } from "./BundleReader";

// A BundleReader for reading a book through a personal picture SET (ADR-0014 Phase 4). A set changes
// only HOW the illustrations look, never the words or which pages carry pictures — so this delegates
// every JSON read (structure/selection/pages) to the base book reader, and draws ONLY images from the
// set's own resident folder: artsets/{user}/{book}/{setId}/…, outside books/{id}/.
//
// The reading path stays 100% offline: image bytes become local Blob object URLs, never a fetch. Because
// Reader hands the active reader down to Plate and Plate's effect keys on the reader instance, swapping
// a StorageBundleReader for one of these (or back) re-resolves every plate — the whole switch mechanism.

export class SetImageBundleReader implements BundleReader {
  private readonly urls = new Map<string, string>();
  /** logical variant group -> actual on-disk relative path within the set (highest `-rN`). */
  private readonly resolved = new Map<string, string>();

  constructor(
    private readonly base: BundleReader,
    private readonly storage: Storage,
    private readonly imageRoot: string,
    setManifest: Manifest,
  ) {
    for (const f of resolveReaderFiles(setManifest)) {
      this.resolved.set(variantKey(f.path).group, f.path);
    }
  }

  /** Text/layout always comes from the book bundle — a set never changes words or anchors. */
  readJson<T>(relPath: string): Promise<T> {
    return this.base.readJson<T>(relPath);
  }

  async imageUrl(relPath: string): Promise<string | null> {
    const cached = this.urls.get(relPath);
    if (cached) return cached;
    const actual = this.resolved.get(variantKey(relPath).group) ?? relPath;
    const abs = `${this.imageRoot}/${actual}`;
    if (!(await this.storage.exists(abs))) return null;
    const bytes = await this.storage.readBytes(abs);
    // Copy into a fresh ArrayBuffer so Blob's BufferSource type is satisfied regardless of the input's
    // backing buffer (Uint8Array is generic over ArrayBufferLike in TS 5.9+).
    const buf = new ArrayBuffer(bytes.byteLength);
    new Uint8Array(buf).set(bytes);
    const url = URL.createObjectURL(new Blob([buf], { type: "image/webp" }));
    this.urls.set(relPath, url);
    return url;
  }

  /** Revoke only the URLs this reader minted; the base reader is owned/disposed by its creator. */
  dispose(): void {
    for (const url of this.urls.values()) URL.revokeObjectURL(url);
    this.urls.clear();
  }
}
