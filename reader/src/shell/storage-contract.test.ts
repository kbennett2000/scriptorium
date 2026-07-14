import { describe, expect, it } from "vitest";

import { MemoryStorage } from "./memory";
import type { Storage } from "./storage";

// The Storage contract, asserted against MemoryStorage — the semantics every backend (OPFS,
// Capacitor) must satisfy. OPFS is unavailable under jsdom, so this is where the interface is pinned;
// OpfsStorage itself is exercised in R1b's real-browser offline run.

function makeStorage(): Storage {
  return new MemoryStorage();
}

describe("Storage contract", () => {
  it("round-trips text", async () => {
    const s = makeStorage();
    await s.writeText("books/x/meta.json", '{"title":"T"}');
    expect(await s.readText("books/x/meta.json")).toBe('{"title":"T"}');
    expect(await s.exists("books/x/meta.json")).toBe(true);
  });

  it("round-trips bytes exactly", async () => {
    const s = makeStorage();
    const bytes = new Uint8Array([0, 1, 2, 253, 254, 255]);
    await s.writeBytes("books/x/images/web/cover.webp", bytes);
    expect([...(await s.readBytes("books/x/images/web/cover.webp"))]).toEqual([...bytes]);
  });

  it("reports absence and lists a subtree", async () => {
    const s = makeStorage();
    expect(await s.exists("books/x/missing")).toBe(false);
    await s.writeText("books/x/pages/0001.json", "a");
    await s.writeText("books/x/pages/0002.json", "b");
    await s.writeText("books/y/pages/0001.json", "c");
    const listed = (await s.list("books/x")).sort();
    expect(listed).toEqual(["books/x/pages/0001.json", "books/x/pages/0002.json"]);
  });

  it("deletes a file and a whole subtree", async () => {
    const s = makeStorage();
    await s.writeText("books/x/a.json", "1");
    await s.writeText("books/x/sub/b.json", "2");
    await s.delete("books/x/a.json");
    expect(await s.exists("books/x/a.json")).toBe(false);
    expect(await s.exists("books/x/sub/b.json")).toBe(true);
    await s.delete("books/x");
    expect(await s.list("books/x")).toEqual([]);
  });

  it("rejects path traversal", async () => {
    const s = makeStorage();
    await expect(s.writeText("books/../secret", "x")).rejects.toThrow(/unsafe/);
  });
});
