import type { Users } from "@scriptorium/shared";

import type { Storage } from "../shell";

// Per-device active profile (DESIGN §14). A single household profile is active at a time, persisted
// locally so a reload skips the picker. The fetched users list is also cached so the Settings
// switcher works offline. No network here — the picker fetches via the SyncClient and hands the list
// down.

const ACTIVE_PATH = "active-profile.json";
const USERS_CACHE_PATH = "users-cache.json";

/** The id of the active household profile, or null if none has been picked yet (first run). */
export async function readActiveProfile(storage: Storage): Promise<string | null> {
  if (!(await storage.exists(ACTIVE_PATH))) return null;
  try {
    const parsed = JSON.parse(await storage.readText(ACTIVE_PATH)) as { id?: string };
    return parsed.id ?? null;
  } catch {
    return null;
  }
}

export async function writeActiveProfile(storage: Storage, id: string): Promise<void> {
  await storage.writeText(ACTIVE_PATH, JSON.stringify({ id }));
}

/** Cache the household roster so the switcher can render offline. */
export async function writeUsersCache(storage: Storage, users: Users): Promise<void> {
  await storage.writeText(USERS_CACHE_PATH, JSON.stringify(users));
}

export async function readUsersCache(storage: Storage): Promise<Users | null> {
  if (!(await storage.exists(USERS_CACHE_PATH))) return null;
  try {
    return JSON.parse(await storage.readText(USERS_CACHE_PATH)) as Users;
  } catch {
    return null;
  }
}
