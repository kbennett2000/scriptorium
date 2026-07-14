import { useCallback, useEffect, useRef, useState } from "react";

import type { Storage } from "../shell";
import { HttpSyncClient } from "./client";
import { readSyncState, syncAllBooks } from "./engine";

// The sync driver (DESIGN §13 triggers). Owns one SyncClient for the app's lifetime and wires the
// four triggers — app foreground (visibilitychange), reconnect (window 'online'), a 10-minute
// interval while reachable, and manual — plus book-close, which App fires by calling `syncNow` on a
// read→shelf transition. Listeners/interval are installed ONCE per profile (not per render), so the
// reading path's page-turns never cause a fetch. Automatic runs use the cached reachability ping;
// manual and reconnect runs force a fresh check so the 60 s cache can't stall a user's intent.

const INTERVAL_MS = 10 * 60 * 1000;

export interface SyncStatus {
  /** null until first checked; false shows the cloud-off indicator. */
  online: boolean | null;
  lastSyncedAt: string | null;
  /** Trigger a sync now. `force` (manual/reconnect) busts the reachability cache. */
  syncNow: (force?: boolean) => Promise<void>;
}

export function useSync(storage: Storage, user: string | null): SyncStatus {
  const clientRef = useRef(new HttpSyncClient());
  const runningRef = useRef(false);
  const [online, setOnline] = useState<boolean | null>(null);
  const [lastSyncedAt, setLastSyncedAt] = useState<string | null>(null);

  const syncNow = useCallback(
    async (force = false) => {
      if (!user || runningRef.current) return;
      runningRef.current = true;
      try {
        const reachable = await clientRef.current.reachable(force);
        setOnline(reachable);
        const outcome = await syncAllBooks(clientRef.current, storage, user, { force });
        if (outcome.ok && outcome.at) setLastSyncedAt(outcome.at);
      } finally {
        runningRef.current = false;
      }
    },
    [storage, user],
  );

  // Load the persisted last-synced marker once.
  useEffect(() => {
    void readSyncState(storage).then((st) => setLastSyncedAt((prev) => prev ?? st.lastSyncedAt));
  }, [storage]);

  // Install triggers once per active profile.
  useEffect(() => {
    if (!user) return;
    void syncNow(false); // initial foreground sync

    const onVisible = () => {
      if (document.visibilityState === "visible") void syncNow(false);
    };
    const onOnline = () => {
      setOnline(true);
      void syncNow(true);
    };
    const onOffline = () => setOnline(false);

    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    const interval = setInterval(() => void syncNow(false), INTERVAL_MS);

    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
      clearInterval(interval);
    };
  }, [user, syncNow]);

  return { online, lastSyncedAt, syncNow };
}
