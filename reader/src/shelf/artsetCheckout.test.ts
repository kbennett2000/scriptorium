import { beforeEach, describe, expect, it } from "vitest";

import type { Manifest } from "@scriptorium/shared";

import { MemoryStorage } from "../shell/memory";
import type { ArtsetClient } from "./artsetCheckout";
import { artsetCheckout, removeSet, setState } from "./artsetCheckout";
import { sha256Hex } from "./checkout";

// Phase 3 (ADR-0014): a private set downloads to artsets/{user}/{book}/{setId}/… outside books/{id},
// sha-verified, resumable, with manifest.local.json written LAST. Shape/paths/verification only.

const USER = "kris";
const BOOK = "usr-000000000000";
const SET = "set-0123456789ab";

// A fake set server backed by an in-memory manifest + bytes. Can corrupt a path to exercise the
// verify/retry path, and counts fetches so resume-skips-good-files is observable.
class FakeArtsetClient implements ArtsetClient {
  fetchCounts: Record<string, number> = {};
  corruptAlways = new Set<string>();

  constructor(
    private manifest: Manifest,
    private bytesByPath: Map<string, Uint8Array>,
  ) {}

  async fetchSetManifest(): Promise<Manifest> {
    return this.manifest;
  }
  async fetchSetFileBytes(
    _u: string,
    _b: string,
    _s: string,
    path: string,
  ): Promise<Uint8Array> {
    this.fetchCounts[path] = (this.fetchCounts[path] ?? 0) + 1;
    if (this.corruptAlways.has(path)) return new Uint8Array([9, 9, 9]);
    const b = this.bytesByPath.get(path);
    if (!b) throw new Error(`404 ${path}`);
    return b;
  }
}

async function makeSet(
  files: Record<string, Uint8Array>,
): Promise<{ manifest: Manifest; bytesByPath: Map<string, Uint8Array> }> {
  const bytesByPath = new Map<string, Uint8Array>();
  const manifestFiles: Manifest["files"] = [];
  for (const [path, bytes] of Object.entries(files)) {
    bytesByPath.set(path, bytes);
    manifestFiles.push({ path, sha256: await sha256Hex(bytes), bytes: bytes.length });
  }
  const manifest: Manifest = {
    book_id: BOOK,
    revision: 1,
    bundle_version: 1,
    content_fingerprint: "0".repeat(64),
    files: manifestFiles,
    reader_required: ["images/web/**", "images/thumbs/**"],
    total_bytes_reader: manifestFiles.reduce((s, f) => s + f.bytes, 0),
  };
  return { manifest, bytesByPath };
}

function setFiles(): Record<string, Uint8Array> {
  return {
    "images/web/cover.webp": new Uint8Array([1, 2, 3, 4]),
    "images/web/plates/0001.webp": new Uint8Array([5, 6, 7, 8]),
    "images/thumbs/cover.webp": new Uint8Array([9, 10]),
  };
}

const localPath = `artsets/${USER}/${BOOK}/${SET}/manifest.local.json`;
const webCover = `artsets/${USER}/${BOOK}/${SET}/images/web/cover.webp`;

describe("artsetCheckout", () => {
  let storage: MemoryStorage;
  beforeEach(() => {
    storage = new MemoryStorage();
  });

  it("downloads a set's images under artsets/{user}/{book}/{setId}/, verified, manifest last", async () => {
    const { manifest, bytesByPath } = await makeSet(setFiles());
    const client = new FakeArtsetClient(manifest, bytesByPath);

    const progress: number[] = [];
    await artsetCheckout(client, storage, USER, BOOK, SET, {
      onProgress: (p) => progress.push(p.done),
    });

    // Every reader-required image landed at the set path (never under books/).
    for (const rel of ["images/web/cover.webp", "images/web/plates/0001.webp", "images/thumbs/cover.webp"]) {
      expect(await storage.exists(`artsets/${USER}/${BOOK}/${SET}/${rel}`)).toBe(true);
    }
    expect((await storage.list("books")).length).toBe(0);
    // Bytes match the source (verified write).
    expect([...(await storage.readBytes(webCover))]).toEqual([1, 2, 3, 4]);
    // The local marker is present and equals the served manifest.
    expect(await storage.exists(localPath)).toBe(true);
    expect(JSON.parse(await storage.readText(localPath))).toEqual(manifest);
    // Progress fired once per resolved file, in order.
    expect(progress).toEqual([1, 2, 3]);
    expect(await setState(storage, USER, BOOK, SET)).toBe("resident");
  });

  it("is incomplete without the local marker, and a re-run resumes (skips good files)", async () => {
    const { manifest, bytesByPath } = await makeSet(setFiles());
    const client = new FakeArtsetClient(manifest, bytesByPath);

    // Simulate an interrupted download: one good file present, no local manifest.
    await storage.writeBytes(webCover, new Uint8Array([1, 2, 3, 4]));
    expect(await setState(storage, USER, BOOK, SET)).toBe("incomplete");

    await artsetCheckout(client, storage, USER, BOOK, SET);

    // The already-good file was NOT re-fetched; the rest were.
    expect(client.fetchCounts["images/web/cover.webp"]).toBeUndefined();
    expect(client.fetchCounts["images/web/plates/0001.webp"]).toBe(1);
    expect(await setState(storage, USER, BOOK, SET)).toBe("resident");
  });

  it("retries a corrupt file then throws, leaving the set incomplete", async () => {
    const { manifest, bytesByPath } = await makeSet(setFiles());
    const client = new FakeArtsetClient(manifest, bytesByPath);
    client.corruptAlways.add("images/web/plates/0001.webp");

    await expect(artsetCheckout(client, storage, USER, BOOK, SET)).rejects.toThrow(/failed sha256/);
    expect(client.fetchCounts["images/web/plates/0001.webp"]).toBe(3); // MAX_ATTEMPTS
    expect(await storage.exists(localPath)).toBe(false);
    expect(await setState(storage, USER, BOOK, SET)).toBe("incomplete");
  });

  it("removeSet deletes only the set subtree, leaving books/ and other sets untouched", async () => {
    const { manifest, bytesByPath } = await makeSet(setFiles());
    await artsetCheckout(new FakeArtsetClient(manifest, bytesByPath), storage, USER, BOOK, SET);
    // A book and a second set exist alongside.
    await storage.writeBytes(`books/${BOOK}/meta.json`, new Uint8Array([1]));
    const other = "set-ffffffffffff";
    await storage.writeBytes(`artsets/${USER}/${BOOK}/${other}/images/web/cover.webp`, new Uint8Array([2]));

    await removeSet(storage, USER, BOOK, SET);

    expect((await storage.list(`artsets/${USER}/${BOOK}/${SET}`)).length).toBe(0);
    expect(await setState(storage, USER, BOOK, SET)).toBe("available");
    expect(await storage.exists(`books/${BOOK}/meta.json`)).toBe(true);
    expect(await storage.exists(`artsets/${USER}/${BOOK}/${other}/images/web/cover.webp`)).toBe(true);
  });
});
