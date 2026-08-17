import type { Manifest } from "@scriptorium/shared";

import type { Storage } from "../shell";
import { resolveReaderFiles, variantKey } from "../shelf/resolve";

// The reading surface's read seam (DESIGN §13). The components consume bundle files through this
// interface only, so they are source-agnostic: a Resident book reads from OPFS `Storage`, the
// `VITE_FIXTURE_BUNDLE` dev mode reads inlined fixtures (see FixtureBundleReader), and tests inject a
// hand-written fake. The reading path performs ZERO network I/O — image bytes become local Blob object
// URLs, never a fetch (ESLint-enforced; readerview/ is outside the shelf/+sync/ allowlist).

export interface BundleReader {
  /** Parse a bundle-relative JSON file (e.g. "structure.json", "pages/0001.json"). */
  readJson<T>(relPath: string): Promise<T>;
  /**
   * A usable image URL for a bundle-relative LOGICAL image path (e.g. "images/web/plates/0001.webp"),
   * or null if the bundle has no such image. Implementations resolve the current `-rN` variant and
   * hand back an object/data URL — the caller never needs to know about revisions.
   */
  imageUrl(relPath: string): Promise<string | null>;
  /**
   * A private per-plate caption override for a page's base plate (ADR-0033), or `undefined` when this
   * reader has no override for it. `undefined` → the caller falls back to the page's auto-derived
   * `best_visual_beat`; a string (including `""`, meaning "show no caption") wins. Only the overlay
   * reader implements this; all others leave it absent.
   */
  captionFor?(pageId: string): string | undefined;
  /**
   * True iff this reader has an accepted video clip for `plateId` in the active scope (ADR-0037) —
   * drives the play icon on the plate. Only the overlay reader implements this; others leave it
   * absent (⇒ no video).
   */
  hasVideo?(plateId: string): boolean;
  /**
   * A usable (offline blob) URL for `plateId`'s accepted clip, or null if none is resident. Like
   * `imageUrl`, the bytes become a local object URL — never a fetch. Only the overlay reader
   * implements this.
   */
  videoUrl?(plateId: string): Promise<string | null>;
  /** Release any object URLs this reader minted. Call on unmount. No-op for data-URL readers. */
  dispose(): void;
}

/**
 * `BundleReader` over a Resident book in `Storage` (OPFS in prod, MemoryStorage in tests). Bundle
 * files live under `books/{bookId}/…`. Image lookups map the logical path to the highest `-rN` variant
 * actually on disk (via the shared resolver), read the bytes, and mint a cached `image/webp` object
 * URL that `dispose()` revokes.
 */
export class StorageBundleReader implements BundleReader {
  private readonly urls = new Map<string, string>();
  /** logical variant group -> actual on-disk relative path (highest `-rN`). */
  private readonly resolved = new Map<string, string>();

  constructor(
    private readonly storage: Storage,
    private readonly bookId: string,
    localManifest: Manifest,
  ) {
    for (const f of resolveReaderFiles(localManifest)) {
      this.resolved.set(variantKey(f.path).group, f.path);
    }
  }

  private abs(rel: string): string {
    return `books/${this.bookId}/${rel}`;
  }

  async readJson<T>(relPath: string): Promise<T> {
    return JSON.parse(await this.storage.readText(this.abs(relPath))) as T;
  }

  async imageUrl(relPath: string): Promise<string | null> {
    const cached = this.urls.get(relPath);
    if (cached) return cached;
    // Substitute the resolved current variant (e.g. 0001-r2.webp) for the logical 0001.webp.
    const actual = this.resolved.get(variantKey(relPath).group) ?? relPath;
    if (!(await this.storage.exists(this.abs(actual)))) return null;
    const bytes = await this.storage.readBytes(this.abs(actual));
    // Copy into a fresh ArrayBuffer so Blob's BufferSource type is satisfied regardless of the input's
    // backing buffer (Uint8Array is generic over ArrayBufferLike in TS 5.9+).
    const buf = new ArrayBuffer(bytes.byteLength);
    new Uint8Array(buf).set(bytes);
    const url = URL.createObjectURL(new Blob([buf], { type: "image/webp" }));
    this.urls.set(relPath, url);
    return url;
  }

  dispose(): void {
    for (const url of this.urls.values()) URL.revokeObjectURL(url);
    this.urls.clear();
  }
}
