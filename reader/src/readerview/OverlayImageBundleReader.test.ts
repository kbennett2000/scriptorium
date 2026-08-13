import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ArtsetEdits, Manifest } from "@scriptorium/shared";

import { MemoryStorage } from "../shell/memory";
import { sha256Hex } from "../shelf/checkout";
import type { BundleReader } from "./BundleReader";
import { OverlayImageBundleReader } from "./OverlayImageBundleReader";

// ADR-0033: the edits overlay overrides ONLY the plates a profile edited (image + caption) and
// delegates everything else to the wrapped base reader. Shape/paths only, never image content.

const USER = "kris";
const BOOK = "usr-000000000000";
const ROOT = `artsets/${USER}/${BOOK}/edits`;

function fakeBase(): BundleReader & { jsonReads: string[]; imageReads: string[] } {
  return {
    jsonReads: [],
    imageReads: [],
    async readJson<T>(rel: string): Promise<T> {
      this.jsonReads.push(rel);
      return { rel } as T;
    },
    async imageUrl(rel: string): Promise<string | null> {
      this.imageReads.push(rel);
      return "base-image-url";
    },
    dispose() {},
  };
}

async function overlayManifest(files: Record<string, Uint8Array>): Promise<Manifest> {
  const entries: Manifest["files"] = [];
  for (const [path, bytes] of Object.entries(files)) {
    entries.push({ path, sha256: await sha256Hex(bytes), bytes: bytes.length });
  }
  return {
    book_id: BOOK,
    revision: 1,
    bundle_version: 1,
    content_fingerprint: "0".repeat(64),
    files: entries,
    reader_required: ["images/web/**", "images/thumbs/**", "edits.json"],
    total_bytes_reader: entries.reduce((s, f) => s + f.bytes, 0),
  };
}

const EDITS: ArtsetEdits = {
  book_id: BOOK,
  user_id: USER,
  source_revision: 1,
  plates: {
    "0001": { caption: "an edited caption", prompt: "p", created: "2026-08-13T00:00:00Z" },
    "0005": { caption: "", prompt: "p", created: "2026-08-13T00:00:00Z" },
  },
};

describe("OverlayImageBundleReader", () => {
  let storage: MemoryStorage;
  beforeEach(() => {
    storage = new MemoryStorage();
    vi.stubGlobal("URL", {
      createObjectURL: vi.fn(() => "blob:overlay-image"),
      revokeObjectURL: vi.fn(),
    });
  });

  it("uses the overlay image for an edited plate, the base for everything else", async () => {
    const edited = new Uint8Array([1, 2, 3]);
    await storage.writeBytes(`${ROOT}/images/web/plates/0001.webp`, edited);
    const base = fakeBase();
    const reader = new OverlayImageBundleReader(
      base, storage, ROOT, await overlayManifest({ "images/web/plates/0001.webp": edited }), EDITS,
    );

    // Edited plate → overlay bytes; base imageUrl never consulted for it.
    expect(await reader.imageUrl("images/web/plates/0001.webp")).toBe("blob:overlay-image");
    expect(base.imageReads).not.toContain("images/web/plates/0001.webp");

    // A plate with no override → delegate to the base reader.
    expect(await reader.imageUrl("images/web/plates/0009.webp")).toBe("base-image-url");
    expect(base.imageReads).toContain("images/web/plates/0009.webp");
  });

  it("delegates all JSON reads to the base reader (words/anchors never change)", async () => {
    const base = fakeBase();
    const reader = new OverlayImageBundleReader(base, storage, ROOT, await overlayManifest({}), EDITS);
    await reader.readJson("pages/0001.json");
    expect(base.jsonReads).toEqual(["pages/0001.json"]);
  });

  it("captionFor returns the override (incl. empty), undefined when there is none", async () => {
    const base = fakeBase();
    const reader = new OverlayImageBundleReader(base, storage, ROOT, await overlayManifest({}), EDITS);
    expect(reader.captionFor("0001")).toBe("an edited caption");
    expect(reader.captionFor("0005")).toBe(""); // explicit "no caption" override
    expect(reader.captionFor("0009")).toBeUndefined(); // no override → caller uses best_visual_beat
  });

  it("falls back to the base image when the overlay file is missing on disk", async () => {
    const edited = new Uint8Array([1]);
    const base = fakeBase();
    // Manifest lists the plate but the bytes were never written to storage.
    const reader = new OverlayImageBundleReader(
      base, storage, ROOT, await overlayManifest({ "images/web/plates/0001.webp": edited }), EDITS,
    );
    expect(await reader.imageUrl("images/web/plates/0001.webp")).toBe("base-image-url");
  });

  it("dispose revokes its own URLs but not the base reader's", async () => {
    const edited = new Uint8Array([7]);
    await storage.writeBytes(`${ROOT}/images/web/plates/0001.webp`, edited);
    const base = fakeBase();
    const disposeSpy = vi.spyOn(base, "dispose");
    const reader = new OverlayImageBundleReader(
      base, storage, ROOT, await overlayManifest({ "images/web/plates/0001.webp": edited }), EDITS,
    );
    await reader.imageUrl("images/web/plates/0001.webp");
    reader.dispose();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:overlay-image");
    expect(disposeSpy).not.toHaveBeenCalled();
  });
});
