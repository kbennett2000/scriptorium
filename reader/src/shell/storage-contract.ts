import type { Storage } from "./storage";

// The Storage contract as backend-agnostic assertions (DESIGN §13, ADR-0006): the exact semantics
// every backend must satisfy — MemoryStorage (tests), OpfsStorage (desktop), CapacitorStorage
// (Android/iOS). Kept free of any test framework so it runs three ways: under vitest against
// MemoryStorage (storage-contract.test.ts) and a mocked plugin (capacitor.test.ts), and inside the
// running Android app against the real @capacitor/filesystem backend (the on-device self-test, R5).
//
// It throws on the first violation with a labelled message; a clean return means the backend conforms.

function assert(cond: boolean, msg: string): asserts cond {
  if (!cond) throw new Error(`Storage contract: ${msg}`);
}

async function rejects(p: Promise<unknown>, match: RegExp): Promise<void> {
  try {
    await p;
  } catch (e) {
    assert(match.test(String(e)), `expected rejection matching ${match}, got: ${String(e)}`);
    return;
  }
  throw new Error(`Storage contract: expected a rejection matching ${match}, but it resolved`);
}

/** Run the full contract against a fresh `Storage` from `make`. Resolves on success; throws on fail. */
export async function runStorageContract(make: () => Storage): Promise<void> {
  // A fresh handle with the shared test namespace wiped first. MemoryStorage isolates per `make()`,
  // but CapacitorStorage (mocked here, real on-device) shares one backing filesystem, so each
  // scenario must clear residue rather than assume a blank store.
  async function fresh(): Promise<Storage> {
    const s = make();
    await s.delete("books");
    return s;
  }

  // round-trips text
  {
    const s = await fresh();
    await s.writeText("books/x/meta.json", '{"title":"T"}');
    assert((await s.readText("books/x/meta.json")) === '{"title":"T"}', "text round-trip");
    assert((await s.exists("books/x/meta.json")) === true, "written text exists");
  }

  // round-trips bytes exactly (full 0x00–0xFF range)
  {
    const s = await fresh();
    const bytes = new Uint8Array([0, 1, 2, 253, 254, 255]);
    await s.writeBytes("books/x/images/web/cover.webp", bytes);
    const got = await s.readBytes("books/x/images/web/cover.webp");
    assert(
      got.length === bytes.length && bytes.every((b, i) => got[i] === b),
      `bytes round-trip: got [${[...got]}]`,
    );
  }

  // reports absence and lists a subtree
  {
    const s = await fresh();
    assert((await s.exists("books/x/missing")) === false, "absent path reports false");
    await s.writeText("books/x/pages/0001.json", "a");
    await s.writeText("books/x/pages/0002.json", "b");
    await s.writeText("books/y/pages/0001.json", "c");
    const listed = (await s.list("books/x")).sort();
    assert(
      listed.length === 2 &&
        listed[0] === "books/x/pages/0001.json" &&
        listed[1] === "books/x/pages/0002.json",
      `list subtree: got [${listed}]`,
    );
  }

  // deletes a file and a whole subtree, idempotently
  {
    const s = await fresh();
    await s.writeText("books/x/a.json", "1");
    await s.writeText("books/x/sub/b.json", "2");
    await s.delete("books/x/a.json");
    assert((await s.exists("books/x/a.json")) === false, "file deleted");
    assert((await s.exists("books/x/sub/b.json")) === true, "sibling survives file delete");
    await s.delete("books/x");
    assert((await s.list("books/x")).length === 0, "subtree deleted");
  }

  // rejects path traversal
  {
    const s = await fresh();
    await rejects(s.writeText("books/../secret", "x"), /unsafe/);
  }
}
