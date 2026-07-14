import { describe, expect, it } from "vitest";

import { MemoryStorage } from "./memory";
import { runStorageContract } from "./storage-contract";

// The Storage contract, asserted against MemoryStorage — the semantics every backend (OPFS,
// Capacitor) must satisfy. The assertions live in ./storage-contract so the same suite also runs
// against a mocked @capacitor/filesystem (capacitor.test.ts) and, on-device, the real Capacitor
// backend (R5 self-test). OPFS is unavailable under jsdom, so this is where the interface is pinned;
// OpfsStorage itself is exercised in R1b's real-browser offline run.

describe("Storage contract", () => {
  it("MemoryStorage satisfies the Storage contract", async () => {
    await expect(runStorageContract(() => new MemoryStorage())).resolves.toBeUndefined();
  });
});
