import type { Annotations, Positions } from "@scriptorium/shared";

import type { Storage } from "../shell";
import type { SyncClient } from "./client";
import { mergeAnnotations } from "./merge";

// The sync engine (DESIGN §13 triggers, §12 merge). Opportunistic and offline-tolerant: it PUTs each
// book's full annotation + position doc to the S12 API and ADOPTS the server's merged answer
// wholesale — the client NEVER field-merges the response (whole-file replace). The mirrored TS merge
// (merge.ts) is used only to canonicalize the LOCAL doc before upload (offline dedup / tombstone
// hygiene), pinned byte-for-byte to the server by the shared vector.
//
// Every path is reachability-guarded and failure is SILENT: a down server or a rejected PUT leaves
// local edits untouched and flips a cloud-off indicator — it is never an exception the reading path
// can see. On success we stamp `sync-state.json` with the time and dispatch a window event so open
// surfaces (Reader/Shelf) can refresh from the freshly-merged files.

const STATE_PATH = "sync-state.json";

/** Fired on `window` after a successful book sync so mounted views can re-read the merged files. */
export const SYNC_EVENT = "scriptorium:synced";

export interface SyncState {
  lastSyncedAt: string | null;
}

export interface SyncOutcome {
  ok: boolean;
  at: string | null;
}

/** Persisted last-synced marker (device-global), shown by the status indicator + settings. */
export async function readSyncState(storage: Storage): Promise<SyncState> {
  if (!(await storage.exists(STATE_PATH))) return { lastSyncedAt: null };
  try {
    return JSON.parse(await storage.readText(STATE_PATH)) as SyncState;
  } catch {
    return { lastSyncedAt: null };
  }
}

async function writeSyncState(storage: Storage, at: string): Promise<void> {
  await storage.writeText(STATE_PATH, JSON.stringify({ lastSyncedAt: at }));
}

/** Local books that have a doc to sync for this user (annotations and/or a saved position). */
async function booksForUser(storage: Storage, user: string): Promise<string[]> {
  const books = new Set<string>();
  for (const prefix of [`annotations/${user}`, `positions/${user}`]) {
    for (const path of await storage.list(prefix)) {
      const rel = path.slice(`${prefix}/`.length);
      if (rel.endsWith(".json") && !rel.includes("/")) books.add(rel.slice(0, -".json".length));
    }
  }
  return [...books];
}

/**
 * Sync one book: PUT the (canonicalized) local annotation doc, adopt the merged result; then the same
 * for positions when a local one exists. Returns true on a fully successful exchange. Any error is
 * swallowed by the caller — this throws so the caller can flip the indicator, but never leaks upward.
 */
async function syncBook(
  client: SyncClient,
  storage: Storage,
  user: string,
  book: string,
): Promise<void> {
  // Annotations: canonicalize locally (dedup/tombstone hygiene) → PUT → adopt server's merged doc.
  const annPath = `annotations/${user}/${book}.json`;
  if (await storage.exists(annPath)) {
    const local = JSON.parse(await storage.readText(annPath)) as Annotations;
    const clean = mergeAnnotations(local, {
      book_id: local.book_id,
      user_id: local.user_id,
      annotations: [],
    });
    const merged = await client.putAnnotations(user, book, clean);
    await storage.writeText(annPath, JSON.stringify(merged));
  }

  // Positions: only when we have a local one (there is no natural empty position). PUT → adopt.
  const posPath = `positions/${user}/${book}.json`;
  if (await storage.exists(posPath)) {
    const local = JSON.parse(await storage.readText(posPath)) as Positions;
    const merged = await client.putPositions(user, book, local);
    await storage.writeText(posPath, JSON.stringify(merged));
  }

  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(SYNC_EVENT, { detail: { book } }));
  }
}

/**
 * Sync every local book for `user`. Reachability-guarded up front (one /health check); returns
 * `{ok:false}` without touching the network when unreachable. A per-book failure marks the whole run
 * not-ok but does not abort the others. `now` is injectable for tests.
 */
export async function syncAllBooks(
  client: SyncClient,
  storage: Storage,
  user: string,
  opts: { force?: boolean; now?: () => Date } = {},
): Promise<SyncOutcome> {
  const now = opts.now ?? (() => new Date());
  if (!(await client.reachable(opts.force))) return { ok: false, at: null };

  let ok = true;
  for (const book of await booksForUser(storage, user)) {
    try {
      await syncBook(client, storage, user, book);
    } catch {
      ok = false; // silent — cloud-off indicator; local edits are preserved
    }
  }

  if (ok) {
    const at = now().toISOString();
    await writeSyncState(storage, at);
    return { ok: true, at };
  }
  return { ok: false, at: null };
}
