import { useEffect, useMemo, useRef, useState } from "react";

import type { Manifest, Users } from "@scriptorium/shared";

import { ProfilePicker, migrateDefaultTo, readActiveProfile, readUsersCache, writeActiveProfile } from "./profiles";
import { Reader, StorageBundleReader, type BundleReader } from "./readerview";
import { Settings, usePrefs } from "./settings";
import { applyStatusBarForTheme, getStorage, initNativeShell } from "./shell";
import type { Storage } from "./shell";
import { Shelf } from "./shelf/Shelf";
import { HttpSyncClient, SyncStatusBadge, useSync, type SyncStatus } from "./sync";

// The reader shell. Two views behind a minimal hash route: `#/` = the shelf, `#/read/{bookId}` = the
// reading surface (so a reload reopens the same book and restores position — a stronger offline story
// than transient in-memory state). VITE_FIXTURE_BUNDLE=1 skips the shelf/network entirely and opens
// the committed fixture book with no backend. Minimal/dense on purpose — the designed skin is R4.
//
// R3 gates the whole app behind a first-run profile picker (DESIGN §14): a per-device active profile
// namespaces all annotation/position files and drives the opportunistic sync engine (see useSync).

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

/** Opens a Resident book: loads its local manifest, builds a StorageBundleReader, renders the Reader. */
function BookReaderView({
  bookId,
  storage,
  user,
  syncStatus,
  onOpenSettings,
}: {
  bookId: string;
  storage: Storage;
  user: string;
  syncStatus: SyncStatus;
  onOpenSettings: () => void;
}) {
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
  return (
    <Reader
      reader={reader}
      storage={storage}
      bookId={bookId}
      user={user}
      syncStatus={syncStatus}
      onOpenSettings={onOpenSettings}
      onExit={exit}
    />
  );
}

/** VITE_FIXTURE_BUNDLE mode: dynamically load the fixture reader (keeps the glob out of prod). */
function FixtureReaderView({
  storage,
  user,
  syncStatus,
  onOpenSettings,
}: {
  storage: Storage;
  user: string;
  syncStatus: SyncStatus;
  onOpenSettings: () => void;
}) {
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
      user={user}
      syncStatus={syncStatus}
      onOpenSettings={onOpenSettings}
      onExit={() => window.location.reload()}
    />
  );
}

export function App() {
  const route = useHashRoute();
  const storage = useMemo(() => getStorage(), []);
  const client = useMemo(() => new HttpSyncClient(), []);
  const fixtureMode = import.meta.env.VITE_FIXTURE_BUNDLE === "1";

  // `undefined` = still reading the persisted choice; `null` = none picked yet (show the gate).
  const [profile, setProfile] = useState<string | null | undefined>(undefined);
  const [users, setUsers] = useState<Users>([]);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const syncStatus = useSync(storage, profile ?? null);
  // Reader display prefs (theme / font size / typeface) applied at the root; per-device, not synced.
  const { prefs, update: updatePrefs } = usePrefs(storage);

  // Wire the native (Android/iOS) shell once: hardware Back routing + status-bar theming. No-op on web.
  useEffect(() => initNativeShell(), []);
  useEffect(() => applyStatusBarForTheme(prefs.theme), [prefs.theme]);

  // Load the persisted active profile once.
  useEffect(() => {
    void readActiveProfile(storage).then((id) => setProfile(id));
  }, [storage]);

  // Keep a local roster for the Settings display (best-effort; the switcher re-fetches if needed).
  useEffect(() => {
    if (!profile) return;
    void readUsersCache(storage).then((cached) => {
      if (cached) setUsers(cached);
    });
  }, [profile, storage]);

  // Book-close sync trigger (DESIGN §13): fire on a read→shelf transition.
  const prevRoute = useRef(route.name);
  useEffect(() => {
    if (prevRoute.current === "read" && route.name === "shelf") void syncStatus.syncNow(false);
    prevRoute.current = route.name;
  }, [route.name, syncStatus]);

  async function pickFirst(id: string) {
    await migrateDefaultTo(storage, id); // one-time: move R2 dev-default data onto the chosen profile
    await writeActiveProfile(storage, id);
    setProfile(id);
  }
  async function switchProfile(id: string) {
    await writeActiveProfile(storage, id);
    setProfile(id);
    setSettingsOpen(false);
  }

  if (profile === undefined) return <main className="app" />;

  if (profile === null) {
    return (
      <main className="app app-picker">
        <ProfilePicker client={client} storage={storage} onPick={(id) => void pickFirst(id)} />
      </main>
    );
  }

  if (settingsOpen) {
    return (
      <main className="app">
        <Settings
          user={profile}
          users={users}
          client={client}
          storage={storage}
          status={syncStatus}
          prefs={prefs}
          onUpdatePrefs={updatePrefs}
          onPickProfile={(id) => void switchProfile(id)}
          onClose={() => setSettingsOpen(false)}
        />
      </main>
    );
  }

  if (fixtureMode) {
    return (
      <main className="app app-reading">
        <FixtureReaderView
          storage={storage}
          user={profile}
          syncStatus={syncStatus}
          onOpenSettings={() => setSettingsOpen(true)}
        />
      </main>
    );
  }

  if (route.name === "read") {
    return (
      <main className="app app-reading">
        <BookReaderView
          bookId={route.bookId}
          storage={storage}
          user={profile}
          syncStatus={syncStatus}
          onOpenSettings={() => setSettingsOpen(true)}
        />
      </main>
    );
  }

  return (
    <main className="app">
      <header className="app-header">
        <h1>Scriptorium</h1>
        <div className="app-header-actions">
          <SyncStatusBadge status={syncStatus} />
          <button type="button" className="settings-open" onClick={() => setSettingsOpen(true)}>
            Settings
          </button>
        </div>
      </header>
      <Shelf />
    </main>
  );
}
