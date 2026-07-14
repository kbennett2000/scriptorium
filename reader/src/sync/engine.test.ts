import { describe, expect, it, vi } from "vitest";

import type { Annotations, Positions, Users } from "@scriptorium/shared";

import { MemoryStorage } from "../shell";
import type { SyncClient } from "./client";
import { SYNC_EVENT, readSyncState, syncAllBooks } from "./engine";
import { mergeAnnotations, mergePositions } from "./merge";

const BOOK = "usr-ce8f5ebd29d0";
const USER = "kris";
const NOW = () => new Date("2026-07-14T12:00:00.000Z");

/** A fake server: stores docs and merges incoming PUTs exactly as S12 does (server-authoritative). */
class FakeServer implements SyncClient {
  up = true;
  anns = new Map<string, Annotations>();
  poss = new Map<string, Positions>();
  putAnnCalls = 0;
  failPut = false;

  async reachable(): Promise<boolean> {
    return this.up;
  }
  async fetchUsers(): Promise<Users> {
    return [{ id: USER, name: "Kris", color: "#000000" }];
  }
  async getAnnotations(user: string, book: string): Promise<Annotations> {
    return this.anns.get(`${user}/${book}`) ?? { book_id: book, user_id: user, annotations: [] };
  }
  async putAnnotations(user: string, book: string, doc: Annotations): Promise<Annotations> {
    this.putAnnCalls += 1;
    if (this.failPut) throw new Error("boom");
    const stored = this.anns.get(`${user}/${book}`) ?? { book_id: book, user_id: user, annotations: [] };
    const merged = mergeAnnotations(stored, doc);
    this.anns.set(`${user}/${book}`, merged);
    return merged;
  }
  async getPositions(user: string, book: string): Promise<Positions | null> {
    return this.poss.get(`${user}/${book}`) ?? null;
  }
  async putPositions(user: string, book: string, doc: Positions): Promise<Positions> {
    const stored = this.poss.get(`${user}/${book}`);
    const merged = stored ? mergePositions(stored, doc) : doc;
    this.poss.set(`${user}/${book}`, merged);
    return merged;
  }
}

function annDoc(mods: Annotations["annotations"]): Annotations {
  return { book_id: BOOK, user_id: USER, annotations: mods };
}

const ann = (id: string, modified: string, deleted = false): Annotations["annotations"][number] => ({
  id,
  type: "highlight",
  page_id: "0001",
  anchor: { start: 0, end: 3 },
  color: "yellow",
  created: "2026-07-14T10:00:00.000Z",
  modified,
  deleted,
});

describe("syncAllBooks", () => {
  it("does nothing and reports not-ok when unreachable", async () => {
    const s = new MemoryStorage();
    await s.writeText(`annotations/${USER}/${BOOK}.json`, JSON.stringify(annDoc([ann("a", "t1")])));
    const server = new FakeServer();
    server.up = false;

    const outcome = await syncAllBooks(server, s, USER, { now: NOW });

    expect(outcome.ok).toBe(false);
    expect(server.putAnnCalls).toBe(0);
  });

  it("PUTs the local doc, adopts the merged result, and stamps last-synced", async () => {
    const s = new MemoryStorage();
    // Server already holds a different annotation; local has its own — they must union.
    const server = new FakeServer();
    server.anns.set(`${USER}/${BOOK}`, annDoc([ann("server-1", "t1")]));
    await s.writeText(`annotations/${USER}/${BOOK}.json`, JSON.stringify(annDoc([ann("local-1", "t2")])));

    const events: string[] = [];
    const listener = (e: Event) => events.push((e as CustomEvent).detail.book);
    window.addEventListener(SYNC_EVENT, listener);

    const outcome = await syncAllBooks(server, s, USER, { now: NOW });
    window.removeEventListener(SYNC_EVENT, listener);

    expect(outcome).toEqual({ ok: true, at: "2026-07-14T12:00:00.000Z" });
    const adopted = JSON.parse(await s.readText(`annotations/${USER}/${BOOK}.json`)) as Annotations;
    expect(adopted.annotations.map((a) => a.id)).toEqual(["local-1", "server-1"]); // union, sorted by id
    expect(events).toEqual([BOOK]);
    expect((await readSyncState(s)).lastSyncedAt).toBe("2026-07-14T12:00:00.000Z");
  });

  it("syncs positions when a local one exists (furthest-wins, current-LWW)", async () => {
    const s = new MemoryStorage();
    const server = new FakeServer();
    server.poss.set(`${USER}/${BOOK}`, {
      furthest: { page_seq: 5, char: 0, modified: "2026-07-14T10:00:00.000Z" },
      current: { page_seq: 5, char: 0, modified: "2026-07-14T10:00:00.000Z", device: "dev-a" },
    });
    await s.writeText(
      `positions/${USER}/${BOOK}.json`,
      JSON.stringify({
        furthest: { page_seq: 3, char: 0, modified: "2026-07-14T11:00:00.000Z" },
        current: { page_seq: 3, char: 0, modified: "2026-07-14T11:00:00.000Z", device: "dev-b" },
      } satisfies Positions),
    );

    await syncAllBooks(server, s, USER, { now: NOW });

    const adopted = JSON.parse(await s.readText(`positions/${USER}/${BOOK}.json`)) as Positions;
    expect(adopted.furthest.page_seq).toBe(5); // furthest never regresses
    expect(adopted.current.page_seq).toBe(3); // later modified wins
  });

  it("is silent on a failed PUT and preserves the local doc", async () => {
    const s = new MemoryStorage();
    const local = annDoc([ann("a", "t1")]);
    await s.writeText(`annotations/${USER}/${BOOK}.json`, JSON.stringify(local));
    const server = new FakeServer();
    server.failPut = true;

    const outcome = await syncAllBooks(server, s, USER, { now: NOW });

    expect(outcome.ok).toBe(false);
    expect(JSON.parse(await s.readText(`annotations/${USER}/${BOOK}.json`))).toEqual(local);
    expect((await readSyncState(s)).lastSyncedAt).toBeNull();
  });

  it("ignores unrelated errors and does not touch the reading path", async () => {
    // No local files at all → nothing to sync, but still a clean ok.
    const s = new MemoryStorage();
    const server = new FakeServer();
    const spy = vi.spyOn(server, "putAnnotations");
    const outcome = await syncAllBooks(server, s, USER, { now: NOW });
    expect(outcome.ok).toBe(true);
    expect(spy).not.toHaveBeenCalled();
  });
});
