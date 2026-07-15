import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Manifest } from "@scriptorium/shared";

import { MemoryStorage } from "../shell/memory";
import { sha256Hex } from "../shelf/checkout";
import type { BundleReader } from "./BundleReader";
import { SetImageBundleReader } from "./SetImageBundleReader";

// Phase 4 (ADR-0014): a set reader delegates text to the book but draws images from the set folder.
// Shape/paths only, never image content.

const USER = "kris";
const BOOK = "usr-000000000000";
const SET = "set-0123456789ab";
const ROOT = `artsets/${USER}/${BOOK}/${SET}`;

// A base (book) reader whose readJson is observable and whose imageUrl must NOT be used by the set.
function fakeBase(): BundleReader & { jsonReads: string[]; imageReads: number } {
  return {
    jsonReads: [],
    imageReads: 0,
    async readJson<T>(rel: string): Promise<T> {
      this.jsonReads.push(rel);
      return { rel } as T;
    },
    async imageUrl(): Promise<string | null> {
      this.imageReads += 1;
      return "book-image-url";
    },
    dispose() {},
  };
}

async function setManifest(files: Record<string, Uint8Array>): Promise<Manifest> {
  const entries: Manifest["files"] = [];
  for (const [path, bytes] of Object.entries(files)) {
    entries.push({ path, sha256: await sha256Hex(bytes), bytes: bytes.length });
  }
  return {
    book_id: BOOK,
    revision: 1,
    bundle_version: 1,
    files: entries,
    reader_required: ["images/web/**", "images/thumbs/**"],
    total_bytes_reader: entries.reduce((s, f) => s + f.bytes, 0),
  };
}

describe("SetImageBundleReader", () => {
  let storage: MemoryStorage;
  beforeEach(() => {
    storage = new MemoryStorage();
    vi.stubGlobal("URL", {
      createObjectURL: vi.fn(() => "blob:set-image"),
      revokeObjectURL: vi.fn(),
    });
  });

  it("reads JSON from the book, images from the set root — never the book's images", async () => {
    const cover = new Uint8Array([1, 2, 3, 4]);
    await storage.writeBytes(`${ROOT}/images/web/cover.webp`, cover);
    const base = fakeBase();
    const reader = new SetImageBundleReader(base, storage, ROOT, await setManifest({
      "images/web/cover.webp": cover,
    }));

    // Text/layout still comes from the book.
    await reader.readJson("structure.json");
    expect(base.jsonReads).toEqual(["structure.json"]);

    // The image resolves from the SET folder; the base reader's imageUrl is never consulted.
    const url = await reader.imageUrl("images/web/cover.webp");
    expect(url).toBe("blob:set-image");
    expect(base.imageReads).toBe(0);
  });

  it("returns null when the set lacks the requested image (no fallback to the book)", async () => {
    const base = fakeBase();
    const reader = new SetImageBundleReader(base, storage, ROOT, await setManifest({}));
    expect(await reader.imageUrl("images/web/plates/0009.webp")).toBeNull();
    expect(base.imageReads).toBe(0);
  });

  it("dispose revokes its own object URLs but not the base reader's", async () => {
    const cover = new Uint8Array([9]);
    await storage.writeBytes(`${ROOT}/images/web/cover.webp`, cover);
    const base = fakeBase();
    const disposeSpy = vi.spyOn(base, "dispose");
    const reader = new SetImageBundleReader(base, storage, ROOT, await setManifest({
      "images/web/cover.webp": cover,
    }));
    await reader.imageUrl("images/web/cover.webp");
    reader.dispose();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:set-image");
    expect(disposeSpy).not.toHaveBeenCalled();
  });
});
