import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ArtsetEdits } from "@scriptorium/shared";

import { MemoryStorage } from "../shell/memory";
import type { BundleReader } from "./BundleReader";
import { OverlayImageBundleReader } from "./OverlayImageBundleReader";

// ADR-0033/0035: the edits overlay overrides ONLY the plates a profile edited (image + caption) FOR
// THE ACTIVE SCOPE, and delegates everything else to the wrapped base reader. So an edit made on the
// comic set overrides the comic set only; switch sets and that set's own picture shows through.
// Shape/paths only, never image content.

const USER = "kris";
const BOOK = "usr-000000000000";
const ROOT = `artsets/${USER}/${BOOK}/edits`;
const COMIC = "set-b0c82de768ce";

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

// 0001 edited on both the base book and the comic set; 0005 edited on the base book only.
const EDITS: ArtsetEdits = {
  book_id: BOOK,
  user_id: USER,
  source_revision: 1,
  plates: {
    "0001": {
      default: { caption: "base caption", prompt: "p", created: "2026-08-13T00:00:00Z" },
      [COMIC]: { caption: "comic caption", prompt: "p", created: "2026-08-13T00:00:00Z" },
    },
    "0005": {
      default: { caption: "", prompt: "p", created: "2026-08-13T00:00:00Z" },
    },
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

  it("uses the scoped overlay image for an edited plate, the base for everything else", async () => {
    const edited = new Uint8Array([1, 2, 3]);
    await storage.writeBytes(`${ROOT}/images/web/plates/default/0001.webp`, edited);
    const base = fakeBase();
    const reader = new OverlayImageBundleReader(base, storage, ROOT, EDITS, "default");

    // Edited plate (this scope) → overlay bytes; base imageUrl never consulted for it.
    expect(await reader.imageUrl("images/web/plates/0001.webp")).toBe("blob:overlay-image");
    expect(base.imageReads).not.toContain("images/web/plates/0001.webp");

    // A plate with no override → delegate to the base reader.
    expect(await reader.imageUrl("images/web/plates/0009.webp")).toBe("base-image-url");
    expect(base.imageReads).toContain("images/web/plates/0009.webp");
  });

  it("only overrides the ACTIVE scope — a comic edit doesn't mask the base book", async () => {
    // Both scopes have a 0001 override on disk.
    await storage.writeBytes(`${ROOT}/images/web/plates/default/0001.webp`, new Uint8Array([1]));
    await storage.writeBytes(`${ROOT}/images/web/plates/${COMIC}/0001.webp`, new Uint8Array([2]));

    // Viewing the base book: 0001 uses the overlay (default scope exists) but reads the DEFAULT file.
    const base1 = fakeBase();
    const onBase = new OverlayImageBundleReader(base1, storage, ROOT, EDITS, "default");
    expect(await onBase.imageUrl("images/web/plates/0001.webp")).toBe("blob:overlay-image");

    // Viewing the comic set: 0005 (edited only on the base book) must delegate to the base reader —
    // the comic set shows its own picture, not the base-book edit.
    const base2 = fakeBase();
    const onComic = new OverlayImageBundleReader(base2, storage, ROOT, EDITS, COMIC);
    expect(await onComic.imageUrl("images/web/plates/0005.webp")).toBe("base-image-url");
    expect(base2.imageReads).toContain("images/web/plates/0005.webp");
  });

  it("ignores a pre-ADR-0035 flat (un-scoped) entry", async () => {
    const legacy = {
      book_id: BOOK,
      user_id: USER,
      source_revision: 1,
      // Old flat shape: the entry sits directly under the plate id, with no scope key.
      plates: { "0001": { caption: "old", prompt: "p", created: "2026-08-13T00:00:00Z" } },
    } as unknown as ArtsetEdits;
    await storage.writeBytes(`${ROOT}/images/web/plates/default/0001.webp`, new Uint8Array([1]));
    const base = fakeBase();
    const reader = new OverlayImageBundleReader(base, storage, ROOT, legacy, "default");
    expect(await reader.imageUrl("images/web/plates/0001.webp")).toBe("base-image-url");
    expect(reader.captionFor("0001")).toBeUndefined();
  });

  it("delegates all JSON reads to the base reader (words/anchors never change)", async () => {
    const base = fakeBase();
    const reader = new OverlayImageBundleReader(base, storage, ROOT, EDITS, "default");
    await reader.readJson("pages/0001.json");
    expect(base.jsonReads).toEqual(["pages/0001.json"]);
  });

  it("captionFor returns the active-scope override (incl. empty), undefined otherwise", async () => {
    const onBase = new OverlayImageBundleReader(fakeBase(), storage, ROOT, EDITS, "default");
    expect(onBase.captionFor("0001")).toBe("base caption");
    expect(onBase.captionFor("0005")).toBe(""); // explicit "no caption" override
    expect(onBase.captionFor("0009")).toBeUndefined(); // no override → caller uses best_visual_beat

    // On the comic set, 0001 resolves to the comic caption; 0005 (base-only) has no comic override.
    const onComic = new OverlayImageBundleReader(fakeBase(), storage, ROOT, EDITS, COMIC);
    expect(onComic.captionFor("0001")).toBe("comic caption");
    expect(onComic.captionFor("0005")).toBeUndefined();
  });

  it("falls back to the base image when the overlay file is missing on disk", async () => {
    const base = fakeBase();
    // 0001 is edited in this scope, but its bytes were never written to storage.
    const reader = new OverlayImageBundleReader(base, storage, ROOT, EDITS, "default");
    expect(await reader.imageUrl("images/web/plates/0001.webp")).toBe("base-image-url");
  });

  it("dispose revokes its own URLs but not the base reader's", async () => {
    await storage.writeBytes(`${ROOT}/images/web/plates/default/0001.webp`, new Uint8Array([7]));
    const base = fakeBase();
    const disposeSpy = vi.spyOn(base, "dispose");
    const reader = new OverlayImageBundleReader(base, storage, ROOT, EDITS, "default");
    await reader.imageUrl("images/web/plates/0001.webp");
    reader.dispose();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:overlay-image");
    expect(disposeSpy).not.toHaveBeenCalled();
  });
});
