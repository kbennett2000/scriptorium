import type { Manifest } from "@scriptorium/shared";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MemoryStorage } from "../shell";
import { StorageBundleReader } from "./BundleReader";
import { FixtureBundleReader } from "./FixtureBundleReader";

// StorageBundleReader is the Resident read path; the fixture reader is the zero-network dev path.
// jsdom implements neither URL.createObjectURL nor revokeObjectURL, so we stub them and assert the
// lifecycle (mint on demand, cache by path, revoke on dispose).

const BOOK = "usr-test000000";

function seed(): { storage: MemoryStorage; manifest: Manifest } {
  const storage = new MemoryStorage();
  const enc = new TextEncoder();
  // A manifest with a base plate AND a -r2 regen for the SAME logical plate → resolver must pick -r2.
  const manifest: Manifest = {
    book_id: BOOK,
    revision: 2,
    bundle_version: 1,
    files: [
      { path: "structure.json", sha256: "0".repeat(64), bytes: 2 },
      { path: "images/web/plates/0001.webp", sha256: "1".repeat(64), bytes: 3 },
      { path: "images/web/plates/0001-r2.webp", sha256: "2".repeat(64), bytes: 3 },
    ],
    reader_required: ["structure.json", "images/web/**"],
    total_bytes_reader: 8,
  };
  storage.writeText(`books/${BOOK}/structure.json`, JSON.stringify({ chapters: [] }));
  // Write ONLY the -r2 variant. If StorageBundleReader resolves correctly it reads this; if it wrongly
  // asked for the base 0001.webp, exists() would be false and imageUrl would return null.
  storage.writeBytes(`books/${BOOK}/images/web/plates/0001-r2.webp`, enc.encode("IMG"));
  return { storage, manifest };
}

describe("StorageBundleReader", () => {
  const created: string[] = [];
  const revoked: string[] = [];

  beforeEach(() => {
    created.length = 0;
    revoked.length = 0;
    URL.createObjectURL = vi.fn(() => {
      const url = `blob:mock/${created.length}`;
      created.push(url);
      return url;
    });
    URL.revokeObjectURL = vi.fn((u: string) => {
      revoked.push(u);
    });
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("reads bundle JSON from books/{id}/", async () => {
    const { storage, manifest } = seed();
    const reader = new StorageBundleReader(storage, BOOK, manifest);
    expect(await reader.readJson<{ chapters: unknown[] }>("structure.json")).toEqual({ chapters: [] });
  });

  it("resolves the logical plate path to the highest -rN variant on disk", async () => {
    const { storage, manifest } = seed();
    const reader = new StorageBundleReader(storage, BOOK, manifest);
    // Ask for the LOGICAL path; only the -r2 file exists, so a non-null URL proves it resolved to -r2.
    const url = await reader.imageUrl("images/web/plates/0001.webp");
    expect(url).toBe("blob:mock/0");
    expect(created).toHaveLength(1);
  });

  it("caches the URL per path and revokes all on dispose", async () => {
    const { storage, manifest } = seed();
    const reader = new StorageBundleReader(storage, BOOK, manifest);
    const a = await reader.imageUrl("images/web/plates/0001.webp");
    const b = await reader.imageUrl("images/web/plates/0001.webp");
    expect(a).toBe(b);
    expect(created).toHaveLength(1); // cached, not re-minted
    reader.dispose();
    expect(revoked).toEqual([a]);
  });

  it("returns null for a logical image the bundle doesn't have", async () => {
    const { storage, manifest } = seed();
    const reader = new StorageBundleReader(storage, BOOK, manifest);
    expect(await reader.imageUrl("images/web/plates/9999.webp")).toBeNull();
  });
});

describe("FixtureBundleReader (zero-network glob)", () => {
  it("reads the committed fixture bundle inlined at build time", async () => {
    const reader = new FixtureBundleReader();
    const meta = await reader.readJson<{ book_id: string; title: string }>("meta.json");
    expect(meta.book_id).toBe("usr-ce8f5ebd29d0");
    expect(meta.title).toBe("The Winter Quay");
  });

  it("returns a usable image URL for a reader plate, null for a missing one", async () => {
    // `?inline` yields a base64 data: URL under `vite build` but a `/@fs/…?inline` URL under vitest's
    // dev transform — either is a usable <img src>. We assert presence here; the built data-URL shape
    // is covered by the VITE_FIXTURE_BUNDLE dev/build smoke (verification step 4).
    const reader = new FixtureBundleReader();
    const url = await reader.imageUrl("images/web/plates/0001.webp");
    expect(typeof url).toBe("string");
    expect(url).toBeTruthy();
    expect(await reader.imageUrl("images/web/plates/9999.webp")).toBeNull();
  });
});
