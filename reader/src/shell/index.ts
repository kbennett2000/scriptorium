// The shell's public surface: the two interfaces plus factories that pick the right host backend.
// Everything above this layer (shelf, readerview, …) depends only on the interfaces, never on a
// concrete backend — the whole point of the seam (ADR-0006).

export type { Storage } from "./storage";
export type { Platform } from "./platform";
export { MemoryStorage } from "./memory";
export { OpfsStorage } from "./opfs";
export { CapacitorStorage } from "./capacitor";
export { BrowserPlatform, CapacitorPlatform } from "./platform";
export { useBackHandler } from "./back";
export { initNativeShell, applyStatusBarForTheme } from "./native";
export { runStorageContract } from "./storage-contract";

import { Capacitor } from "@capacitor/core";

import type { Storage } from "./storage";
import type { Platform } from "./platform";
import { OpfsStorage } from "./opfs";
import { CapacitorStorage } from "./capacitor";
import { BrowserPlatform, CapacitorPlatform } from "./platform";

/**
 * The `Storage` backend for the current host: the Capacitor filesystem on a native (Android/iOS)
 * build, OPFS in the desktop PWA. `isNativePlatform()` is false in the browser and under tests, so
 * the web/e2e path is unchanged (ADR-0006 — swapping backends is a shell swap, nothing above cares).
 */
export function getStorage(): Storage {
  return Capacitor.isNativePlatform() ? new CapacitorStorage() : new OpfsStorage();
}

export function getPlatform(): Platform {
  return Capacitor.isNativePlatform() ? new CapacitorPlatform() : new BrowserPlatform();
}
