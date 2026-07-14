import { useCallback, useEffect, useMemo, useState } from "react";

import { getPlatform, getStorage } from "../shell";
import type { BookState, CheckoutProgress, LibraryEntry } from "./index";
import { HttpLibraryClient, bookState, checkout, remove } from "./index";

// The shelf screen (DESIGN §13). Reachability-guarded library listing with Resident/Available cards,
// download-with-progress, and remove-keeps-annotations. Deliberately minimal/dense — the designed
// skin is R4; opening a Resident book into the reading surface is R1b.

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function Shelf() {
  const client = useMemo(() => new HttpLibraryClient(), []);
  const storage = useMemo(() => getStorage(), []);

  const [online, setOnline] = useState<boolean | null>(null);
  const [entries, setEntries] = useState<LibraryEntry[]>([]);
  const [states, setStates] = useState<Record<string, BookState>>({});
  const [progress, setProgress] = useState<Record<string, CheckoutProgress | undefined>>({});
  const [error, setError] = useState<string | null>(null);

  const refreshState = useCallback(
    async (id: string) => {
      const st = await bookState(storage, id);
      setStates((prev) => ({ ...prev, [id]: st }));
    },
    [storage],
  );

  const load = useCallback(async () => {
    setError(null);
    try {
      const up = await client.reachable();
      setOnline(up);
      if (!up) return;
      const lib = await client.fetchLibrary();
      setEntries(lib);
      await Promise.all(lib.map((e) => refreshState(e.id)));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [client, refreshState]);

  useEffect(() => {
    void load();
  }, [load]);

  const download = useCallback(
    async (id: string) => {
      setProgress((prev) => ({ ...prev, [id]: { file: "", done: 0, total: 0 } }));
      try {
        await checkout(client, storage, id, {
          platform: getPlatform(),
          onProgress: (p) => setProgress((prev) => ({ ...prev, [id]: p })),
        });
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setProgress((prev) => ({ ...prev, [id]: undefined }));
        await refreshState(id);
      }
    },
    [client, storage, refreshState],
  );

  const removeBook = useCallback(
    async (id: string) => {
      const ok = window.confirm(
        "Remove this book from the device? Your annotations are kept — they sync separately.",
      );
      if (!ok) return;
      await remove(storage, id);
      await refreshState(id);
    },
    [storage, refreshState],
  );

  return (
    <section className="shelf">
      <div className="shelf-status">
        {online === null ? "Checking server…" : online ? "Online" : "Offline — showing owned books"}
        <button type="button" onClick={() => void load()}>
          Refresh
        </button>
      </div>
      {error && <p className="shelf-error">{error}</p>}
      <ul className="shelf-list">
        {entries.map((e) => {
          const state = states[e.id] ?? "available";
          const prog = progress[e.id];
          return (
            <li key={e.id} className="shelf-card">
              <div className="shelf-card-head">
                <strong>{e.title}</strong>
                <span className="shelf-author">{e.author}</span>
              </div>
              <div className="shelf-card-meta">
                rev {e.revision} · {formatBytes(e.total_bytes_reader)} · {state}
              </div>
              <div className="shelf-card-actions">
                {state === "resident" ? (
                  <>
                    <button
                      type="button"
                      className="shelf-open"
                      onClick={() => {
                        window.location.hash = `#/read/${encodeURIComponent(e.id)}`;
                      }}
                    >
                      Open
                    </button>
                    <span className="shelf-resident">Resident ✓</span>
                    <button type="button" onClick={() => void removeBook(e.id)}>
                      Remove
                    </button>
                  </>
                ) : prog ? (
                  <span className="shelf-progress">
                    Downloading {prog.done}/{prog.total}…
                  </span>
                ) : (
                  <button type="button" onClick={() => void download(e.id)}>
                    {state === "incomplete" ? "Resume download" : "Download"}
                  </button>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
