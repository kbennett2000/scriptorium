import { beforeEach, describe, expect, it, vi } from "vitest";

// CapacitorStorage against a mocked @capacitor/filesystem. The fake models native semantics —
// path-addressed files, directories inferred from paths, `recursive` writes, subtree `rmdir`, and
// `stat`/`readdir`/`deleteFile` throwing on the wrong kind or a missing path — so the SAME Storage
// contract that MemoryStorage passes pins CapacitorStorage's path-walk + base64 logic in CI, with no
// emulator. The real backend is re-verified on-device by the R5 self-test (identical runStorageContract).

/** A minimal in-memory stand-in for the native Filesystem, keyed by `/`-joined path under one root. */
const files = new Map<string, string>(); // path -> stored data string (base64 or UTF-8, opaque here)

function isDir(path: string): boolean {
  const prefix = path === "" ? "" : `${path}/`;
  for (const key of files.keys()) if (key.startsWith(prefix)) return true;
  return false;
}

vi.mock("@capacitor/filesystem", () => {
  return {
    Directory: { Data: "DATA" },
    Encoding: { UTF8: "utf8" },
    Filesystem: {
      writeFile: vi.fn(async ({ path, data }: { path: string; data: string }) => {
        files.set(path, data);
        return { uri: `file:///${path}` };
      }),
      readFile: vi.fn(async ({ path }: { path: string }) => {
        if (!files.has(path)) throw new Error(`File does not exist: ${path}`);
        return { data: files.get(path)! };
      }),
      stat: vi.fn(async ({ path }: { path: string }) => {
        if (!files.has(path) && !isDir(path)) throw new Error(`File does not exist: ${path}`);
        return { type: files.has(path) ? "file" : "directory", size: 0, mtime: 0, uri: path };
      }),
      deleteFile: vi.fn(async ({ path }: { path: string }) => {
        if (!files.has(path)) throw new Error(`not a file: ${path}`); // dir or missing → caller falls back to rmdir
        files.delete(path);
      }),
      rmdir: vi.fn(async ({ path }: { path: string }) => {
        if (!isDir(path)) throw new Error(`Folder does not exist: ${path}`);
        for (const key of [...files.keys()]) if (key.startsWith(`${path}/`)) files.delete(key);
      }),
      readdir: vi.fn(async ({ path }: { path: string }) => {
        if (path !== "" && !isDir(path)) throw new Error(`Folder does not exist: ${path}`);
        const prefix = path === "" ? "" : `${path}/`;
        const names = new Map<string, "file" | "directory">();
        for (const key of files.keys()) {
          if (!key.startsWith(prefix)) continue;
          const rest = key.slice(prefix.length);
          const slash = rest.indexOf("/");
          if (slash === -1) names.set(rest, "file");
          else names.set(rest.slice(0, slash), "directory");
        }
        return {
          files: [...names].map(([name, type]) => ({ name, type, size: 0, mtime: 0, uri: name })),
        };
      }),
    },
  };
});

import { CapacitorStorage } from "./capacitor";
import { runStorageContract } from "./storage-contract";

describe("CapacitorStorage", () => {
  beforeEach(() => files.clear());

  it("satisfies the Storage contract over a mocked @capacitor/filesystem", async () => {
    await expect(runStorageContract(() => new CapacitorStorage())).resolves.toBeUndefined();
  });

  it("stores bytes as base64 and decodes them byte-exactly", async () => {
    const s = new CapacitorStorage();
    const bytes = new Uint8Array([0, 1, 2, 127, 128, 253, 254, 255]);
    await s.writeBytes("b/raw.bin", bytes);
    // The mock kept exactly what the backend handed the plugin — a base64 string, not raw bytes.
    expect(files.get("b/raw.bin")).toBe(btoa(String.fromCharCode(...bytes)));
    expect([...(await s.readBytes("b/raw.bin"))]).toEqual([...bytes]);
  });
});
