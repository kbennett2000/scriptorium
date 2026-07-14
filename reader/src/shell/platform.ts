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
