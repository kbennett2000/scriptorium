import type { Storage } from "../shell";

// Per-device active picture set for a (profile, book): which set of illustrations the reader shows
// (DESIGN §8, ADR-0014). Persisted locally so a reopen restores the choice. The default is "default"
// — the shipped bundle art every profile starts on. No network here: switching between resident sets
// is fully offline, and a set only changes how the pictures look, never the page text/layout.

export const DEFAULT_SET_ID = "default";

function activeSetPath(user: string, bookId: string): string {
  return `artsets-active/${user}/${bookId}.json`;
}

/** The active set id for (user, book), or "default" if none has been chosen. */
export async function readActiveSet(
  storage: Storage,
  user: string,
  bookId: string,
): Promise<string> {
  const path = activeSetPath(user, bookId);
  if (!(await storage.exists(path))) return DEFAULT_SET_ID;
  try {
    const parsed = JSON.parse(await storage.readText(path)) as { set_id?: string };
    return parsed.set_id ?? DEFAULT_SET_ID;
  } catch {
    return DEFAULT_SET_ID;
  }
}

export async function writeActiveSet(
  storage: Storage,
  user: string,
  bookId: string,
  setId: string,
): Promise<void> {
  await storage.writeText(activeSetPath(user, bookId), JSON.stringify({ set_id: setId }));
}
