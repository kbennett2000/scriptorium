import type { ArtsetEdits } from "@scriptorium/shared";

import type { Storage } from "../shell";
import type { BundleReader } from "./BundleReader";

// A BundleReader that layers a household profile's PRIVATE per-plate edits (ADR-0033) over whatever
// reader is active — the base book or a personal style set. Edits are SCOPED to the reader they were
// made from (ADR-0035): this overlay is built for the ACTIVE scope ("default" for the base book, or a
// "set-…" id) and only surfaces an edit filed under that same scope. So an edit made on the comic set
// overrides the comic set only; switch to Cyberpunk and its own picture shows through. For an edited
// plate the image (and, for a base plate, the caption) come from the overlay at
// artsets/{user}/{book}/edits/images/{web,thumbs}/plates/{scope}/{plate_id}.…; every other plate, and
// all text/JSON, delegate to the wrapped `base` reader. So this composes on TOP of
// SetImageBundleReader (or StorageBundleReader) without replacing it.
//
// Like the other readers the reading path stays 100% offline: image bytes become local Blob object
// URLs, never a fetch. `dispose()` revokes only the URLs this reader minted; the wrapped base reader
// is owned (and disposed) by its own creator.

// A `images/web/plates/0001.webp` (or thumbs) request → its (dir, plate_id). Only these two dirs are
// editable; anything else delegates untouched. Extras keep their `{page}-N` id in the filename stem.
const PLATE_PATH_RE = /^(images\/(?:web|thumbs)\/plates)\/([^/]+)\.webp$/;

export class OverlayImageBundleReader implements BundleReader {
  private readonly urls = new Map<string, string>();
  /** plate_id -> the profile's caption override for it, for the active scope only. */
  private readonly captions = new Map<string, string>();
  /** plate_ids the profile has an edit for IN THE ACTIVE SCOPE (so we know when to look at all). */
  private readonly edited = new Set<string>();
  /** plate_ids that have an accepted video clip in the active scope (ADR-0037). */
  private readonly videos = new Set<string>();

  constructor(
    private readonly base: BundleReader,
    private readonly storage: Storage,
    private readonly imageRoot: string,
    edits: ArtsetEdits | null,
    /** The active reader's scope: "default" for the base book, or a "set-…" id. */
    private readonly scope: string,
  ) {
    for (const [plateId, byScope] of Object.entries(edits?.plates ?? {})) {
      // ADR-0035 shape is plates[plate_id][scope]; a pre-0035 flat entry has no scope key, so
      // `[scope]` is undefined and it is ignored (it can't be attributed to a reader).
      const entry = (byScope as Record<string, { caption?: string; video?: unknown }> | null)?.[
        scope
      ];
      if (!entry || typeof entry.caption !== "string") continue;
      this.edited.add(plateId);
      this.captions.set(plateId, entry.caption);
      // ADR-0037: a `video` descriptor on the entry means an accepted clip is filed under
      // images/video/plates/{scope}/{plate_id}.mp4 — surface a play icon for it.
      if (entry.video) this.videos.add(plateId);
    }
  }

  /** Text/layout always comes from the wrapped reader — an edit never changes words or anchors. */
  readJson<T>(relPath: string): Promise<T> {
    return this.base.readJson<T>(relPath);
  }

  /** The scoped overlay path for an edited plate's image request, or null to delegate untouched. */
  private overlayPath(relPath: string): string | null {
    const m = PLATE_PATH_RE.exec(relPath);
    if (!m) return null;
    const [, dir, plateId] = m;
    if (!this.edited.has(plateId)) return null;
    return `${dir}/${this.scope}/${plateId}.webp`;
  }

  async imageUrl(relPath: string): Promise<string | null> {
    const overlayRel = this.overlayPath(relPath);
    if (overlayRel === null) return this.base.imageUrl(relPath); // not edited in this scope
    const cached = this.urls.get(relPath);
    if (cached) return cached;
    const abs = `${this.imageRoot}/${overlayRel}`;
    if (!(await this.storage.exists(abs))) return this.base.imageUrl(relPath);
    const bytes = await this.storage.readBytes(abs);
    const buf = new ArrayBuffer(bytes.byteLength);
    new Uint8Array(buf).set(bytes);
    const url = URL.createObjectURL(new Blob([buf], { type: "image/webp" }));
    this.urls.set(relPath, url);
    return url;
  }

  /** The profile's caption for this base plate in the active scope, or `undefined` if none. */
  captionFor(pageId: string): string | undefined {
    return this.captions.get(pageId);
  }

  /** True iff the profile accepted a clip for this plate in the active scope (ADR-0037). */
  hasVideo(plateId: string): boolean {
    return this.videos.has(plateId);
  }

  /** An offline blob URL for the plate's accepted clip, or null if there is none / not resident. */
  async videoUrl(plateId: string): Promise<string | null> {
    if (!this.videos.has(plateId)) return null;
    const key = `video:${plateId}`;
    const cached = this.urls.get(key);
    if (cached) return cached;
    const abs = `${this.imageRoot}/images/video/plates/${this.scope}/${plateId}.mp4`;
    if (!(await this.storage.exists(abs))) return null;
    const bytes = await this.storage.readBytes(abs);
    const buf = new ArrayBuffer(bytes.byteLength);
    new Uint8Array(buf).set(bytes);
    const url = URL.createObjectURL(new Blob([buf], { type: "video/mp4" }));
    this.urls.set(key, url);
    return url;
  }

  dispose(): void {
    for (const url of this.urls.values()) URL.revokeObjectURL(url);
    this.urls.clear();
  }
}
