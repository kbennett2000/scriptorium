import { describe, expect, it } from "vitest";

import type { BundleReader } from "../readerview/BundleReader";
import { MemoryStorage } from "../shell";
import {
  buildCount,
  buildIndex,
  deserializeIndex,
  ensureIndex,
  indexPath,
  searchPages,
  serializeIndex,
  snippet,
  type IndexedPage,
} from ".";

// Search core (DESIGN §13): the index must build, round-trip through toJSON/loadJSON identically, and —
// the load-bearing property — LOAD from disk on reopen with NO rebuild (so reload is instant and the
// build cost is paid once). We prove the last via the build counter and a reader that refuses reads.

const PAGES: IndexedPage[] = [
  { id: "0001", seq: 1, text: "The quiet harbour lay under a cold grey sky." },
  { id: "0002", seq: 2, text: "A lantern swung on the fog-bound quay as the tide turned." },
  { id: "0003", seq: 3, text: "Bells rang across the water and the wanderer walked on." },
];

/** A BundleReader that serves the fixture pages — and records whether it was read. */
function fakeReader(seen: string[]): BundleReader {
  return {
    async readJson<T>(relPath: string): Promise<T> {
      seen.push(relPath);
      const id = relPath.replace("pages/", "").replace(".json", "");
      const page = PAGES.find((p) => p.id === id);
      if (!page) throw new Error(`unexpected readJson: ${relPath}`);
      return page as unknown as T;
    },
    async imageUrl() {
      return null;
    },
    dispose() {},
  };
}

const BOOK = "usr-0123456789ab";
const pageIds = PAGES.map((p) => p.id);

describe("search index", () => {
  it("builds, round-trips via toJSON/loadJSON, and finds a mid-book phrase", () => {
    const ms = buildIndex(PAGES);
    const restored = deserializeIndex(serializeIndex(ms));

    for (const idx of [ms, restored]) {
      const hits = searchPages(idx, "lantern");
      expect(hits.map((h) => h.seq)).toEqual([2]);
      expect(hits[0].terms).toContain("lantern");
    }
  });

  it("prefix-matches and returns no results for an empty query", () => {
    const ms = buildIndex(PAGES);
    expect(searchPages(ms, "wander").map((h) => h.seq)).toEqual([3]);
    expect(searchPages(ms, "   ")).toEqual([]);
  });

  it("ensureIndex builds + persists once, then LOADS on reopen with no rebuild", async () => {
    const storage = new MemoryStorage();
    const before = buildCount();

    const seen1: string[] = [];
    const first = await ensureIndex(storage, fakeReader(seen1), BOOK, pageIds);
    expect(searchPages(first, "harbour").map((h) => h.seq)).toEqual([1]);
    expect(buildCount()).toBe(before + 1); // one real build
    expect(seen1.length).toBe(PAGES.length); // read every page to build
    expect(await storage.exists(indexPath(BOOK))).toBe(true); // persisted

    // Reopen: the reader would THROW if read — proving we loaded from disk, not rebuilt.
    const seen2: string[] = [];
    const throwingReader: BundleReader = {
      async readJson<T>(): Promise<T> {
        throw new Error("must not read pages on reopen");
      },
      async imageUrl() {
        return null;
      },
      dispose() {},
    };
    const second = await ensureIndex(storage, throwingReader, BOOK, pageIds);
    expect(searchPages(second, "harbour").map((h) => h.seq)).toEqual([1]);
    expect(buildCount()).toBe(before + 1); // STILL one build — no rebuild on reopen
    expect(seen2.length).toBe(0);
  });

  it("snippet windows around the first matching term", () => {
    const s = snippet(PAGES[2].text, ["wanderer"]);
    expect(s.toLowerCase()).toContain("wanderer");
    expect(s.length).toBeLessThanOrEqual(PAGES[2].text.length + 2);
  });
});
