import type { ArtsetEdits, Manifest } from "@scriptorium/shared";

import type { Storage } from "../shell";
import { resolveReaderFiles, variantKey } from "../shelf/resolve";
import type { BundleReader } from "./BundleReader";

// A BundleReader that layers a household profile's PRIVATE per-plate edits (ADR-0033) over whatever
// reader is active — the base book or a personal style set. For a plate the profile has edited, the
// image (and, for a base plate, the caption) come from the overlay at artsets/{user}/{book}/edits/;
// every other plate, and all text/JSON, delegate to the wrapped `base` reader. So this composes on
// TOP of SetImageBundleReader (or StorageBundleReader) without replacing it.
//
// Like the other readers the reading path stays 100% offline: image bytes become local Blob object
// URLs, never a fetch. `dispose()` revokes only the URLs this reader minted; the wrapped base reader
// is owned (and disposed) by its own creator.

export class OverlayImageBundleReader implements BundleReader {
  private readonly urls = new Map<string, string>();
  /** logical variant group -> actual on-disk relative path within the overlay. */
  private readonly resolved = new Map<string, string>();
  /** plate_id -> the profile's caption override for it. */
  private readonly captions = new Map<string, string>();

  constructor(
    private readonly base: BundleReader,
    private readonly storage: Storage,
    private readonly imageRoot: string,
    manifest: Manifest,
    edits: ArtsetEdits | null,
  ) {
    for (const f of resolveReaderFiles(manifest)) {
      this.resolved.set(variantKey(f.path).group, f.path);
    }
    for (const [plateId, edit] of Object.entries(edits?.plates ?? {})) {
      this.captions.set(plateId, edit.caption);
    }
  }

  /** Text/layout always comes from the wrapped reader — an edit never changes words or anchors. */
  readJson<T>(relPath: string): Promise<T> {
    return this.base.readJson<T>(relPath);
  }

  async imageUrl(relPath: string): Promise<string | null> {
    const group = variantKey(relPath).group;
    const actual = this.resolved.get(group);
    if (actual === undefined) return this.base.imageUrl(relPath); // not edited → wrapped reader
    const cached = this.urls.get(relPath);
    if (cached) return cached;
    const abs = `${this.imageRoot}/${actual}`;
    if (!(await this.storage.exists(abs))) return this.base.imageUrl(relPath);
    const bytes = await this.storage.readBytes(abs);
    const buf = new ArrayBuffer(bytes.byteLength);
    new Uint8Array(buf).set(bytes);
    const url = URL.createObjectURL(new Blob([buf], { type: "image/webp" }));
    this.urls.set(relPath, url);
    return url;
  }

  /** The profile's caption for this base plate, or `undefined` if it has no override for it. */
  captionFor(pageId: string): string | undefined {
    return this.captions.get(pageId);
  }

  dispose(): void {
    for (const url of this.urls.values()) URL.revokeObjectURL(url);
    this.urls.clear();
  }
}
