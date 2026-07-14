import { useCallback, useEffect, useState } from "react";

import type { Storage } from "../shell";
import { applyPrefs, DEFAULT_PREFS, readPrefs, writePrefs, type Prefs } from "./prefs";

// Owns the reader's display preferences at the App root so every screen themes consistently. Loads +
// applies persisted prefs on mount; `update` merges a patch, applies it immediately (instant feedback),
// and persists in the background. Persistence is per-device (settings/prefs.json), never synced.

export interface PrefsController {
  prefs: Prefs;
  update: (patch: Partial<Prefs>) => void;
}

export function usePrefs(storage: Storage): PrefsController {
  const [prefs, setPrefs] = useState<Prefs>(DEFAULT_PREFS);

  useEffect(() => {
    void readPrefs(storage).then((p) => {
      setPrefs(p);
      applyPrefs(p);
    });
  }, [storage]);

  const update = useCallback(
    (patch: Partial<Prefs>) => {
      setPrefs((prev) => {
        const next = { ...prev, ...patch };
        applyPrefs(next);
        void writePrefs(storage, next);
        return next;
      });
    },
    [storage],
  );

  return { prefs, update };
}
