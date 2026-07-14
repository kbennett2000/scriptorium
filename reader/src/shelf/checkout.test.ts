import { beforeEach, describe, expect, it } from "vitest";

import type { Manifest } from "@scriptorium/shared";

import { MemoryStorage } from "../shell/memory";
import type { LibraryClient, LibraryEntry } from "./client";
import { bookState, checkout, delta, remove, sha256Hex } from "./checkout";

const BOOK = "usr-000000000000";

// A fake library server backed by an in-memory bundle. Counts fetches per path and can corrupt a
// path's bytes (transiently or permanently) so the checkout's verify/retry/resume paths are testable.
class FakeClient implements LibraryClient {
  fetchCounts: Record<string, number> = {};
  corruptOnce = new Set<string>();
  corruptAlways = new Set<string>();

  constructor(
    private manifest: Manifest,
    private bytesByPath: Map<string, Uint8Array>,
  ) {}

  setBundle(manifest: Manifest, bytesByPath: Map<string, Uint8Array>) {
    this.manifest = manifest;
    this.bytesByPath = bytesByPath;
  }

  async reachable(): Promise<boolean> {
    return true;
  }
  async fetchLibrary(): Promise<LibraryEntry[]> {
    return [];
  }
  async fetchManifest(): Promise<Manifest> {
    return this.manifest;
  }
  async fetchFileBytes(_id: string, path: string): Promise<Uint8Array> {
    this.fetchCounts[path] = (this.fetchCounts[path] ?? 0) + 1;
    if (this.corruptAlways.has(path)) return new Uint8Array([9, 9, 9]);
    if (this.corruptOnce.has(path) && this.fetchCounts[path] === 1) return new Uint8Array([9, 9, 9]);
    const b = this.bytesByPath.get(path);
    if (!b) throw new Error(`404 ${path}`);
    return b;
  }
}

async function makeBundle(
  files: Record<string, Uint8Array>,
  revision = 1,
): Promise<{ manifest: Manifest; bytesByPath: Map<string, Uint8Array> }> {
  const bytesByPath = new Map<string, Uint8Array>();
  const manifestFiles: Manifest["files"] = [];
  for (const [path, bytes] of Object.entries(files)) {
    bytesByPath.set(path, bytes);
    manifestFiles.push({ path, sha256: await sha256Hex(bytes), bytes: bytes.length });
  }
  const manifest: Manifest = {
    book_id: BOOK,
    revision,
    bundle_version: 1,
    files: manifestFiles,
    reader_required: ["meta.json", "pages/*", "images/web/**", "images/thumbs/**"],
    total_bytes_reader: manifestFiles.reduce((s, f) => s + f.bytes, 0),
  };
  return { manifest, bytesByPath };
}

function bundleFiles(): Record<string, Uint8Array> {
  return {
    "meta.json": new TextEncoder().encode('{"title":"The Winter Quay"}'),
    "pages/0001.json": new TextEncoder().encode('{"id":"0001"}'),
    "images/web/plates/0001.webp": new Uint8Array([1, 2, 3, 4]),
    "images/thumbs/plates/0001.webp": new Uint8Array([5, 6, 7]),
  };
}

describe("checkout", () => {
  let storage: MemoryStorage;
  beforeEach(() => {
    storage = new MemoryStorage();
  });

  it("downloads, verifies, and becomes Resident", async () => {
    const { manifest, bytesByPath } = await makeBundle(bundleFiles());
    const client = new FakeClient(manifest, bytesByPath);

    expect(await bookState(storage, BOOK)).toBe("available");
    await checkout(client, storage, BOOK);
    expect(await bookState(storage, BOOK)).toBe("resident");

    // Every resolved file is on disk with the right bytes; each fetched exactly once.
    expect([...(await storage.readBytes(`books/${BOOK}/images/web/plates/0001.webp`))]).toEqual([
      1, 2, 3, 4,
    ]);
    expect(await storage.exists(`books/${BOOK}/manifest.local.json`)).toBe(true);
    for (const p of Object.keys(bundleFiles())) expect(client.fetchCounts[p]).toBe(1);
  });

  it("retries ONLY the corrupt file, then completes", async () => {
    const { manifest, bytesByPath } = await makeBundle(bundleFiles());
    const client = new FakeClient(manifest, bytesByPath);
    client.corruptOnce.add("images/web/plates/0001.webp"); // bad bytes on first fetch only

    await checkout(client, storage, BOOK);
    expect(await bookState(storage, BOOK)).toBe("resident");
    expect(client.fetchCounts["images/web/plates/0001.webp"]).toBe(2); // one retry
    expect(client.fetchCounts["meta.json"]).toBe(1); // others untouched
  });

  it("leaves the book Incomplete on hard failure, then resumes fetching only the bad file", async () => {
    const { manifest, bytesByPath } = await makeBundle(bundleFiles());
    const client = new FakeClient(manifest, bytesByPath);
    const bad = "images/thumbs/plates/0001.webp";
    client.corruptAlways.add(bad);

    await expect(checkout(client, storage, BOOK)).rejects.toThrow(/sha256/);
    expect(await bookState(storage, BOOK)).toBe("incomplete");
    expect(await storage.exists(`books/${BOOK}/manifest.local.json`)).toBe(false);
    expect(await storage.exists(`books/${BOOK}/meta.json`)).toBe(true); // good files landed
    const goodCountBefore = client.fetchCounts["meta.json"];

    client.corruptAlways.delete(bad); // server heals
    await checkout(client, storage, BOOK);
    expect(await bookState(storage, BOOK)).toBe("resident");
    expect(client.fetchCounts["meta.json"]).toBe(goodCountBefore); // good files NOT refetched
  });

  it("delta fetches only changed files and prunes removed ones", async () => {
    const v1 = await makeBundle(bundleFiles());
    const client = new FakeClient(v1.manifest, v1.bytesByPath);
    await checkout(client, storage, BOOK);
    const countAfterV1 = { ...client.fetchCounts };

    // Revision 2: one page changes; the thumb is dropped from the bundle.
    const v2files = bundleFiles();
    v2files["pages/0001.json"] = new TextEncoder().encode('{"id":"0001","rev":2}');
    delete v2files["images/thumbs/plates/0001.webp"];
    const v2 = await makeBundle(v2files, 2);
    client.setBundle(v2.manifest, v2.bytesByPath);

    const result = await delta(client, storage, BOOK);
    expect(result.fetched).toEqual(["pages/0001.json"]);
    expect(result.pruned).toEqual(["images/thumbs/plates/0001.webp"]);
    // Unchanged web plate was not refetched by delta.
    expect(client.fetchCounts["images/web/plates/0001.webp"]).toBe(
      countAfterV1["images/web/plates/0001.webp"],
    );
    expect(await storage.exists(`books/${BOOK}/images/thumbs/plates/0001.webp`)).toBe(false);
    const local = JSON.parse(await storage.readText(`books/${BOOK}/manifest.local.json`));
    expect(local.revision).toBe(2);
  });

  it("remove deletes the book but keeps annotations", async () => {
    const { manifest, bytesByPath } = await makeBundle(bundleFiles());
    const client = new FakeClient(manifest, bytesByPath);
    await checkout(client, storage, BOOK);
    await storage.writeText(`sync/kris/${BOOK}.json`, '{"annotations":[]}'); // lives outside books/

    await remove(storage, BOOK);
    expect(await bookState(storage, BOOK)).toBe("available");
    expect(await storage.list(`books/${BOOK}`)).toEqual([]);
    expect(await storage.exists(`sync/kris/${BOOK}.json`)).toBe(true); // annotations survive
  });
});
