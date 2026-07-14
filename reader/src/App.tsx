import { useEffect, useMemo, useState } from "react";

import type { Manifest } from "@scriptorium/shared";

import { Reader, StorageBundleReader, type BundleReader } from "./readerview";
import { getStorage } from "./shell";
import type { Storage } from "./shell";
import { Shelf } from "./shelf/Shelf";

// The reader shell. Two views behind a minimal hash route: `#/` = the shelf, `#/read/{bookId}` = the
// reading surface (so a reload reopens the same book and restores position — a stronger offline story
// than transient in-memory state). VITE_FIXTURE_BUNDLE=1 skips the shelf/network entirely and opens
// the committed fixture book with no backend. Minimal/dense on purpose — the designed skin is R4.

type Route = { name: "shelf" } | { name: "read"; bookId: string };

function parseHash(): Route {
  const m = /^#\/read\/(.+)$/.exec(window.location.hash);
  return m ? { name: "read", bookId: decodeURIComponent(m[1]) } : { name: "shelf" };
}

function useHashRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseHash());
  useEffect(() => {
    const onHash = () => setRoute(parseHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  return route;
}

/** Unobtrusive "storage protected" indicator (§13 asks to surface persist status somewhere). */
function PersistBadge() {
  const [persisted, setPersisted] = useState<boolean | null>(null);
  useEffect(() => {
    if (!navigator.storage?.persisted) return;
    void navigator.storage.persisted().then(setPersisted);
  }, []);
  if (persisted === null) return null;
  return (
    <span className="persist-badge" title="Whether the browser has protected this book from eviction">
      storage protected: {persisted ? "yes" : "no"}
    </span>
  );
}

/** Opens a Resident book: loads its local manifest, builds a StorageBundleReader, renders the Reader. */
function BookReaderView({ bookId, storage }: { bookId: string; storage: Storage }) {
  const [reader, setReader] = useState<BundleReader | null>(null);
  const [error, setError] = useState<string | null>(null);
  const exit = () => {
    window.location.hash = "#/";
  };

  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const raw = await storage.readText(`books/${bookId}/manifest.local.json`);
        const manifest = JSON.parse(raw) as Manifest;
        if (live) setReader(new StorageBundleReader(storage, bookId, manifest));
      } catch (e) {
        if (live) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      live = false;
    };
  }, [bookId, storage]);

  if (error) {
    return (
      <section className="reader">
        <button type="button" className="reader-back" onClick={exit}>
          ← Shelf
        </button>
        <p className="shelf-error">This book isn’t resident: {error}</p>
      </section>
    );
  }
  if (!reader) return <p className="reader-loading">Opening…</p>;
  return <Reader reader={reader} storage={storage} bookId={bookId} onExit={exit} />;
}

/** VITE_FIXTURE_BUNDLE mode: dynamically load the fixture reader (keeps the glob out of prod). */
function FixtureReaderView({ storage }: { storage: Storage }) {
  const [state, setState] = useState<{ reader: BundleReader; bookId: string } | null>(null);
  useEffect(() => {
    let live = true;
    void import("./readerview/FixtureBundleReader").then((m) => {
      if (live) setState({ reader: new m.FixtureBundleReader(), bookId: m.FIXTURE_BOOK_ID });
    });
    return () => {
      live = false;
    };
  }, []);
  if (!state) return <p className="reader-loading">Loading fixture…</p>;
  return (
    <Reader
      reader={state.reader}
      storage={storage}
      bookId={state.bookId}
      onExit={() => window.location.reload()}
    />
  );
}

export function App() {
  const route = useHashRoute();
  const storage = useMemo(() => getStorage(), []);
  const fixtureMode = import.meta.env.VITE_FIXTURE_BUNDLE === "1";

  if (fixtureMode) {
    return (
      <main className="app app-reading">
        <FixtureReaderView storage={storage} />
        <PersistBadge />
      </main>
    );
  }

  if (route.name === "read") {
    return (
      <main className="app app-reading">
        <BookReaderView bookId={route.bookId} storage={storage} />
        <PersistBadge />
      </main>
    );
  }

  return (
    <main className="app">
      <header className="app-header">
        <h1>Scriptorium</h1>
      </header>
      <Shelf />
      <PersistBadge />
    </main>
  );
}
