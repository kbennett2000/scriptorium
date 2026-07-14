// The shell's public surface: the two interfaces plus factories that pick the right host backend.
// Everything above this layer (shelf, readerview, …) depends only on the interfaces, never on a
// concrete backend — the whole point of the seam (ADR-0006).

export type { Storage } from "./storage";
export type { Platform } from "./platform";
export { MemoryStorage } from "./memory";
export { OpfsStorage } from "./opfs";
export { CapacitorStorage } from "./capacitor";
export { BrowserPlatform } from "./platform";

import type { Storage } from "./storage";
import type { Platform } from "./platform";
import { OpfsStorage } from "./opfs";
import { BrowserPlatform } from "./platform";

/**
 * The `Storage` backend for the current host. v1 desktop PWA → OPFS; the Capacitor backend
 * (Android/iOS) is selected here in R5. Falls back to OPFS, which surfaces a clear error if the
 * host truly lacks it rather than silently doing nothing.
 */
export function getStorage(): Storage {
  return new OpfsStorage();
}

export function getPlatform(): Platform {
  return new BrowserPlatform();
}
