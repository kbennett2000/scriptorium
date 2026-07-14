import { describe, expect, it } from "vitest";

import { MemoryStorage } from "../shell";
import { migrateDefaultTo } from "./migrate";

const BOOK = "usr-ce8f5ebd29d0";

describe("migrateDefaultTo", () => {
  it("moves dev-default annotations and un-namespaced positions under {user}/", async () => {
    const s = new MemoryStorage();
    await s.writeText(`annotations/default/${BOOK}.json`, '{"book_id":"x","user_id":"default","annotations":[]}');
    await s.writeText(`positions/${BOOK}.json`, '{"furthest":{"page_seq":1,"char":0,"modified":"t"}}');

    await migrateDefaultTo(s, "kris");

    expect(await s.exists(`annotations/kris/${BOOK}.json`)).toBe(true);
    expect(await s.exists(`positions/kris/${BOOK}.json`)).toBe(true);
    expect(await s.exists(`annotations/default/${BOOK}.json`)).toBe(false);
    expect(await s.exists(`positions/${BOOK}.json`)).toBe(false);
    // Content is preserved byte-for-byte.
    expect(await s.readText(`positions/kris/${BOOK}.json`)).toBe(
      '{"furthest":{"page_seq":1,"char":0,"modified":"t"}}',
    );
  });

  it("is a no-op for the dev-default user itself", async () => {
    const s = new MemoryStorage();
    await s.writeText(`annotations/default/${BOOK}.json`, "{}");
    await migrateDefaultTo(s, "default");
    expect(await s.exists(`annotations/default/${BOOK}.json`)).toBe(true);
  });

  it("is idempotent — a second run with nothing to move does nothing", async () => {
    const s = new MemoryStorage();
    await s.writeText(`annotations/default/${BOOK}.json`, "{}");
    await migrateDefaultTo(s, "kris");
    const after = (await s.list("")).sort();
    await migrateDefaultTo(s, "kris");
    expect((await s.list("")).sort()).toEqual(after);
  });

  it("does not clobber an existing destination", async () => {
    const s = new MemoryStorage();
    await s.writeText(`annotations/default/${BOOK}.json`, "OLD");
    await s.writeText(`annotations/kris/${BOOK}.json`, "KEEP");
    await migrateDefaultTo(s, "kris");
    expect(await s.readText(`annotations/kris/${BOOK}.json`)).toBe("KEEP");
    expect(await s.exists(`annotations/default/${BOOK}.json`)).toBe(false);
  });

  it("leaves already-namespaced positions alone", async () => {
    const s = new MemoryStorage();
    await s.writeText(`positions/kris/${BOOK}.json`, "KEEP");
    await migrateDefaultTo(s, "kris");
    expect(await s.readText(`positions/kris/${BOOK}.json`)).toBe("KEEP");
  });
});
