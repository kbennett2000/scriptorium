import { describe, expect, it } from "vitest";

import type { Manifest } from "@scriptorium/shared";

import { MemoryStorage } from "../shell";
import { residentEntries } from "./checkout";

// residentEntries lists owned books straight from storage — the offline shelf path (DESIGN §13). The
// shelf used to leave its list empty when the server was unreachable, so a kill/relaunch offline hid
// every downloaded book; this pins the fix.

function manifest(bookId: string, revision: number): Manifest {
  return {
    book_id: bookId,
    revision,
    bundle_version: 1,
    total_bytes_reader: 0,
    reader_required: ["meta.json", "pages/*"],
    files: [
      { path: "meta.json", sha256: "a".repeat(64), bytes: 20 },
      { path: "pages/0001.json", sha256: "b".repeat(64), bytes: 80 },
    ],
  };
}

async function seedResident(s: MemoryStorage, id: string, title: string, rev = 1): Promise<void> {
  await s.writeText(`books/${id}/manifest.local.json`, JSON.stringify(manifest(id, rev)));
  await s.writeText(`books/${id}/meta.json`, JSON.stringify({ title, author: `${title} author` }));
}

describe("residentEntries (offline shelf listing)", () => {
  it("returns nothing when no book is resident", async () => {
    expect(await residentEntries(new MemoryStorage())).toEqual([]);
  });

  it("lists resident books with title/author/revision/size from local storage", async () => {
    const s = new MemoryStorage();
    await seedResident(s, "usr-bbb", "Beta", 2);
    await seedResident(s, "usr-aaa", "Alpha", 1);

    const entries = await residentEntries(s);
    expect(entries.map((e) => e.title)).toEqual(["Alpha", "Beta"]); // sorted by title
    expect(entries[0]).toMatchObject({
      id: "usr-aaa",
      title: "Alpha",
      author: "Alpha author",
      revision: 1,
      total_bytes_reader: 100, // meta.json (20) + pages/0001.json (80)
    });
  });

  it("still lists a book whose meta.json is missing, falling back to its id as title", async () => {
    const s = new MemoryStorage();
    await s.writeText("books/usr-ccc/manifest.local.json", JSON.stringify(manifest("usr-ccc", 1)));
    const entries = await residentEntries(s);
    expect(entries).toHaveLength(1);
    expect(entries[0]).toMatchObject({ id: "usr-ccc", title: "usr-ccc", author: "" });
  });
});
