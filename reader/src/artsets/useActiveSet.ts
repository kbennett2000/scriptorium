import { useCallback, useEffect, useState } from "react";

import type { Storage } from "../shell";

import { DEFAULT_SET_ID, readActiveSet, writeActiveSet } from "./activeSet";

// Loads the active picture set for (user, book) and exposes a setter that persists the choice
// locally. Fully offline (DESIGN §8, ADR-0014). Phase 1: switching is a no-op on the pictures
// themselves (only the default set exists) — the persistence + wiring land now; the image-source
// swap arrives in a later cycle.

export function useActiveSet(storage: Storage, user: string, bookId: string) {
  const [activeSetId, setActiveSetId] = useState<string>(DEFAULT_SET_ID);

  useEffect(() => {
    let live = true;
    void readActiveSet(storage, user, bookId).then((id) => {
      if (live) setActiveSetId(id);
    });
    return () => {
      live = false;
    };
  }, [storage, user, bookId]);

  const chooseSet = useCallback(
    async (setId: string) => {
      setActiveSetId(setId);
      await writeActiveSet(storage, user, bookId, setId);
    },
    [storage, user, bookId],
  );

  return { activeSetId, chooseSet };
}
