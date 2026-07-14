import type { Positions } from "@scriptorium/shared";

import type { Storage } from "../shell";

// Local reading-position persistence (DESIGN §13, §12). A position is `{page_seq, char}` where `char`
// is the approximate top-visible UTF-16 offset (paragraph granularity — see pagetext.topVisibleChar).
// R1b persists positions LOCALLY only; R3 owns the sync merge/upload. The on-disk shape already matches
// positions.schema so R3 can lift these files straight into the merge:
//   furthest = max by tuple (page_seq, char) regardless of timestamp (furthest-read-wins)
//   current  = last write wins
//
// Positions live at `positions/{user}/{bookId}.json` — OUTSIDE `books/{bookId}/`, so shelf `remove`
// (which deletes only `books/{id}/`) keeps them. This is what the shelf's "annotations are kept" copy
// promises. R3 namespaces positions by profile (mirroring annotations and the server's {user}/{book}
// sync layout); R1b's un-namespaced `positions/{bookId}.json` files are migrated by `profiles/migrate`.

export interface Point {
  page_seq: number;
  char: number;
}

const DEVICE_ID_PATH = "device-id.json";

function positionsPath(user: string, bookId: string): string {
  return `positions/${user}/${bookId}.json`;
}

/** A stable per-install device label (positions.current.device), generated once and reused. */
export async function deviceId(storage: Storage): Promise<string> {
  if (await storage.exists(DEVICE_ID_PATH)) {
    try {
      const parsed = JSON.parse(await storage.readText(DEVICE_ID_PATH)) as { id?: string };
      if (parsed.id) return parsed.id;
    } catch {
      // fall through and regenerate on a corrupt file
    }
  }
  const id = crypto.randomUUID();
  await storage.writeText(DEVICE_ID_PATH, JSON.stringify({ id }));
  return id;
}

/** Read a book's saved positions, or null if none exist yet / the file is unreadable. */
export async function readPosition(
  storage: Storage,
  user: string,
  bookId: string,
): Promise<Positions | null> {
  const path = positionsPath(user, bookId);
  if (!(await storage.exists(path))) return null;
  try {
    return JSON.parse(await storage.readText(path)) as Positions;
  } catch {
    return null;
  }
}

/** furthest-read-wins: does `a`'s (page_seq, char) tuple strictly exceed `b`'s? */
function isBeyond(a: Point, b: Point): boolean {
  if (a.page_seq !== b.page_seq) return a.page_seq > b.page_seq;
  return a.char > b.char;
}

/**
 * Persist `point` as the current position for `bookId`, advancing `furthest` only if this is the
 * furthest point ever reached (and keeping the prior furthest's own `modified` when it isn't).
 * `modified` on the values we write is an ISO-8601 UTC timestamp; `now` is injectable for tests.
 */
export async function writePosition(
  storage: Storage,
  user: string,
  bookId: string,
  point: Point,
  device: string,
  now: () => Date = () => new Date(),
): Promise<Positions> {
  const modified = now().toISOString();
  const existing = await readPosition(storage, user, bookId);
  const furthest =
    existing && !isBeyond(point, existing.furthest)
      ? existing.furthest
      : { page_seq: point.page_seq, char: point.char, modified };
  const positions: Positions = {
    furthest,
    current: { page_seq: point.page_seq, char: point.char, modified, device },
  };
  await storage.writeText(positionsPath(user, bookId), JSON.stringify(positions));
  return positions;
}
