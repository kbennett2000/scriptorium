// Platform-capability seam (DESIGN §13) — the small set of host powers the app needs beyond storage.
// v1 needs only `persistHint`; `share` is reserved for a later cycle.

export interface Platform {
  /**
   * Ask the host to protect our storage from eviction (desktop: `navigator.storage.persist()`).
   * Returns whether storage is now persistent. Surfaced in Settings ("storage protected: yes/no",
   * R4). Called on first checkout.
   */
  persistHint(): Promise<boolean>;
}

export class BrowserPlatform implements Platform {
  async persistHint(): Promise<boolean> {
    if (!navigator.storage?.persist) return false;
    try {
      return await navigator.storage.persist();
    } catch {
      return false;
    }
  }
}

// Android/iOS host (R5). Capacitor stores our bundles under `Directory.Data` — the app-private data
// directory — which the OS does NOT evict under storage pressure the way a browser evicts OPFS; it
// persists until the app is uninstalled or its data is explicitly cleared. There is therefore no
// `navigator.storage.persist()` analogue to request: storage is already durable, so `persistHint`
// reports the granted-equivalent `true`. Surfaced by Settings' "storage protected" row.
export class CapacitorPlatform implements Platform {
  async persistHint(): Promise<boolean> {
    return true;
  }
}
