import { DEV_USER_ID } from "../annotations";
import type { Storage } from "../shell";

// One-time migration of the R2 dev-default data onto the profile chosen at first run (DESIGN §14).
// R2 wrote annotations under `annotations/default/{book}.json` (a hardcoded DEV_USER_ID) and R1b
// wrote positions UN-namespaced at `positions/{book}.json`. When the picker lands and the household
// chooses a real profile, that data must move under `{user}/` so it namespaces and syncs correctly.
//
// Invoked exactly once — App only calls it on the FIRST pick (when no active profile was set yet).
// Still written to be idempotent and non-destructive: it never clobbers an existing destination, and
// a re-run with nothing to move is a no-op.

/**
 * Move `annotations/default/*` → `annotations/{user}/*` and top-level `positions/{book}.json` →
 * `positions/{user}/{book}.json`. No-op when `user` is the dev default (nothing to migrate onto).
 */
export async function migrateDefaultTo(storage: Storage, user: string): Promise<void> {
  if (user === DEV_USER_ID) return;

  // Annotations: everything under the dev-default namespace.
  const annPrefix = `annotations/${DEV_USER_ID}/`;
  for (const path of await storage.list(`annotations/${DEV_USER_ID}`)) {
    if (!path.startsWith(annPrefix)) continue;
    const rel = path.slice(annPrefix.length);
    const dest = `annotations/${user}/${rel}`;
    if (!(await storage.exists(dest))) {
      await storage.writeText(dest, await storage.readText(path));
    }
  }
  await storage.delete(`annotations/${DEV_USER_ID}`);

  // Positions: only the un-namespaced top-level files (`positions/{book}.json`), not any already
  // moved under `positions/{user}/`.
  for (const path of await storage.list("positions")) {
    const rel = path.slice("positions/".length);
    if (rel.includes("/")) continue; // already namespaced — leave it
    const dest = `positions/${user}/${rel}`;
    if (!(await storage.exists(dest))) {
      await storage.writeText(dest, await storage.readText(path));
    }
    await storage.delete(path);
  }
}
