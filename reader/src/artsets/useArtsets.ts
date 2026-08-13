import { useCallback, useEffect, useRef, useState } from "react";

import type { ArtsetList } from "@scriptorium/shared";

import type { Storage } from "../shell";
import type { ArtsetApi, StyleOption } from "../shelf";
import type { ArtsetClient, SetState } from "../shelf";
import { artsetCheckout, removeSet, setState } from "../shelf";
import { DEFAULT_SET_ID } from "./activeSet";
import { useActiveSet } from "./useActiveSet";

// The "Pictures" menu's state machine (ADR-0014 Phase 4). Owns the list of a user's sets for a book,
// each row's local residency, the art-style catalog, and the make → poll → download → switch flow — so
// SetPicker stays presentational. Reading a resident set is fully offline; making/downloading/deleting
// need the home server, and gracefully degrade when it's unreachable (Default + already-downloaded sets
// stay usable). A set only ever changes images, never the book's words.

const POLL_MS = 2000;

type Summary = ArtsetList["sets"][number];

/** A picker row: the server summary + this device's residency + any in-flight download progress. */
export type SetRow = Summary & {
  residency: SetState;
  progress?: { done: number; total: number } | null;
};

export interface Artsets {
  sets: SetRow[];
  styles: StyleOption[];
  /** Installed base models a new set may render with (ADR-0030); empty when imagegen is unreachable. */
  models: string[];
  online: boolean;
  busy: boolean;
  error: string | null;
  activeSetId: string;
  /** Switch to a set (downloading it first if it's ready but not yet on this device). */
  choose: (setId: string) => Promise<void>;
  /** Make a new set — a chosen style, or a re-roll of the book's style. Auto-downloads + switches. */
  create: (
    kind: "style" | "reroll",
    styleId?: string,
    model?: string | null,
    customStyle?: string | null,
  ) => Promise<void>;
  /** Delete a personal set (server + this device); reverts to Default if it was active. */
  remove: (setId: string) => Promise<void>;
  /** Retry a failed set: delete it, then make a fresh one with the same style. */
  retry: (setId: string) => Promise<void>;
}

const DEFAULT_ROW: SetRow = {
  set_id: DEFAULT_SET_ID,
  kind: "default",
  label: "Default",
  status: "ready",
  residency: "resident",
};

function listCachePath(user: string, book: string): string {
  return `artsets-active/${user}/${book}.list.json`;
}

export function useArtsets(
  api: ArtsetApi,
  download: ArtsetClient,
  storage: Storage,
  user: string,
  book: string,
  open: boolean,
  pollMs: number = POLL_MS,
): Artsets {
  const { activeSetId, chooseSet } = useActiveSet(storage, user, book);
  const [sets, setSets] = useState<SetRow[]>([DEFAULT_ROW]);
  const [styles, setStyles] = useState<StyleOption[]>([]);
  const [models, setModels] = useState<string[]>([]);
  const [online, setOnline] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // A just-created set awaiting ready → auto-download → auto-switch; and a guard against double download.
  const pendingRef = useRef<string | null>(null);
  const downloadingRef = useRef<Set<string>>(new Set());

  const setProgress = useCallback((setId: string, p: { done: number; total: number } | null) => {
    setSets((prev) => prev.map((r) => (r.set_id === setId ? { ...r, progress: p } : r)));
  }, []);

  const withResidency = useCallback(
    async (summaries: Summary[]): Promise<SetRow[]> => {
      const rows: SetRow[] = [];
      for (const s of summaries) {
        const residency: SetState =
          s.set_id === DEFAULT_SET_ID ? "resident" : await setState(storage, user, book, s.set_id);
        rows.push({ ...s, residency });
      }
      return rows;
    },
    [storage, user, book],
  );

  // Download a set to this device (if needed), then make it the active one.
  const ensureResidentAndChoose = useCallback(
    async (setId: string): Promise<void> => {
      if (setId !== DEFAULT_SET_ID && downloadingRef.current.has(setId)) return;
      const residency = await setState(storage, user, book, setId);
      if (setId !== DEFAULT_SET_ID && residency !== "resident") {
        downloadingRef.current.add(setId);
        setBusy(true);
        try {
          await artsetCheckout(download, storage, user, book, setId, {
            onProgress: (p) => setProgress(setId, { done: p.done, total: p.total }),
          });
        } finally {
          downloadingRef.current.delete(setId);
          setBusy(false);
          setProgress(setId, null);
        }
      }
      await chooseSet(setId);
      setSets((prev) =>
        prev.map((r) => (r.set_id === setId ? { ...r, residency: "resident", progress: null } : r)),
      );
    },
    [download, storage, user, book, chooseSet, setProgress],
  );

  const refresh = useCallback(async (): Promise<void> => {
    let list: ArtsetList | null = null;
    try {
      list = await api.fetchSetList(user, book);
    } catch {
      list = null;
    }
    if (list) {
      setOnline(true);
      try {
        await storage.writeText(listCachePath(user, book), JSON.stringify(list));
      } catch {
        // Cache is best-effort; a write failure must not break the online path.
      }
      const rows = await withResidency(list.sets);
      setSets(rows);
      // Auto-advance a just-created set once the server reports it ready (or failed).
      const pend = pendingRef.current;
      if (pend) {
        const row = rows.find((r) => r.set_id === pend);
        if (!row || row.status === "failed") {
          pendingRef.current = null;
          if (row?.status === "failed") setError("Couldn’t make that set — please try again.");
        } else if (row.status === "ready") {
          pendingRef.current = null;
          await ensureResidentAndChoose(pend);
        }
      }
    } else {
      setOnline(false);
      let cached: ArtsetList | null = null;
      try {
        cached = JSON.parse(await storage.readText(listCachePath(user, book))) as ArtsetList;
      } catch {
        cached = null;
      }
      const summaries = cached?.sets ?? [DEFAULT_ROW];
      const rows = await withResidency(summaries);
      // Offline: only Default + sets already on this device are usable.
      setSets(rows.filter((r) => r.set_id === DEFAULT_SET_ID || r.residency === "resident"));
    }
  }, [api, storage, user, book, withResidency, ensureResidentAndChoose]);

  // Load the list (and, once, the style catalog) whenever the menu opens.
  useEffect(() => {
    if (!open) return;
    void refresh();
  }, [open, refresh]);

  useEffect(() => {
    if (!open || !online || styles.length > 0) return;
    let live = true;
    void api
      .fetchStyles()
      .then((s) => {
        if (live) setStyles(s);
      })
      .catch(() => {
        /* styles are optional chrome; the reroll option works without them */
      });
    return () => {
      live = false;
    };
  }, [open, online, styles.length, api]);

  // Load the installed base-model list once per open (ADR-0030). Best-effort: a failure leaves the
  // list empty, so the picker just omits the model chooser and the server uses its default.
  useEffect(() => {
    if (!open || !online || models.length > 0) return;
    let live = true;
    void api
      .fetchModels()
      .then((m) => {
        if (live) setModels(m.models);
      })
      .catch(() => {
        /* models are optional advanced chrome; sets render fine on the service default */
      });
    return () => {
      live = false;
    };
  }, [open, online, models.length, api]);

  // Poll while any set is still generating (or a create is pending), until it settles.
  useEffect(() => {
    if (!open || !online) return;
    const waiting = pendingRef.current !== null || sets.some((s) => s.status === "generating");
    if (!waiting) return;
    const t = setTimeout(() => void refresh(), pollMs);
    return () => clearTimeout(t);
  }, [open, online, sets, refresh, pollMs]);

  const choose = useCallback(
    async (setId: string): Promise<void> => {
      setError(null);
      try {
        await ensureResidentAndChoose(setId);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Couldn’t switch pictures.");
      }
    },
    [ensureResidentAndChoose],
  );

  const create = useCallback(
    async (
      kind: "style" | "reroll",
      styleId?: string,
      model?: string | null,
      customStyle?: string | null,
    ): Promise<void> => {
      setBusy(true);
      setError(null);
      try {
        const made = await api.createSet(user, book, {
          kind,
          style_id: styleId,
          model,
          custom_style: customStyle,
        });
        pendingRef.current = made.set_id;
        await refresh();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Couldn’t start making that set.");
      } finally {
        setBusy(false);
      }
    },
    [api, user, book, refresh],
  );

  const remove = useCallback(
    async (setId: string): Promise<void> => {
      setBusy(true);
      setError(null);
      try {
        await api.deleteSet(user, book, setId);
        await removeSet(storage, user, book, setId);
        if (activeSetId === setId) await chooseSet(DEFAULT_SET_ID);
        await refresh();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Couldn’t delete that set.");
      } finally {
        setBusy(false);
      }
    },
    [api, storage, user, book, activeSetId, chooseSet, refresh],
  );

  // Retry a failed set by remaking it with the same style — the failed one has no usable output, so
  // dropping it and creating afresh (reusing the pending→auto-download→switch flow) is the whole job.
  const retry = useCallback(
    async (setId: string): Promise<void> => {
      const failed = sets.find((r) => r.set_id === setId);
      if (!failed) return;
      await remove(setId);
      await create(failed.kind === "reroll" ? "reroll" : "style", failed.style_id);
    },
    [sets, remove, create],
  );

  return { sets, styles, models, online, busy, error, activeSetId, choose, create, remove, retry };
}
