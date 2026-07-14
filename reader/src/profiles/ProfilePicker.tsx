import { useEffect, useState } from "react";

import type { Users } from "@scriptorium/shared";

import type { SyncClient } from "../sync";
import { readUsersCache, writeUsersCache } from "./activeProfile";
import type { Storage } from "../shell";

// First-run profile picker (DESIGN §14, ADR-0005 LAN trust — no passwords). Avatar circles (the
// profile's accent color + initial) and name, fetched from GET /api/users via the injected
// SyncClient. Also the Settings switcher target. The roster is cached locally so a later switch works
// offline; on a cold first run with no server and no cache, we surface a retry.

/** One tappable avatar circle. */
function Avatar({ color, name }: { color: string; name: string }) {
  return (
    <span className="profile-avatar" style={{ backgroundColor: color }} aria-hidden="true">
      {name.trim().charAt(0).toUpperCase()}
    </span>
  );
}

export function ProfilePicker({
  client,
  storage,
  onPick,
  heading = "Who's reading?",
}: {
  client: SyncClient;
  storage: Storage;
  onPick: (userId: string) => void;
  heading?: string;
}) {
  const [users, setUsers] = useState<Users | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let live = true;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const fetched = await client.fetchUsers();
        if (!live) return;
        setUsers(fetched);
        await writeUsersCache(storage, fetched);
      } catch {
        // Offline / server down: fall back to a cached roster if we have one.
        const cached = await readUsersCache(storage);
        if (!live) return;
        if (cached && cached.length) setUsers(cached);
        else setError("Can’t reach the library to load profiles.");
      } finally {
        if (live) setLoading(false);
      }
    })();
    return () => {
      live = false;
    };
  }, [client, storage, attempt]);

  return (
    <section className="profile-picker">
      <h2>{heading}</h2>
      {loading && <p className="profile-loading">Loading profiles…</p>}
      {!loading && error && (
        <div className="profile-error">
          <p>{error}</p>
          <button type="button" onClick={() => setAttempt((a) => a + 1)}>
            Retry
          </button>
        </div>
      )}
      {users && (
        <ul className="profile-list">
          {users.map((u) => (
            <li key={u.id}>
              <button type="button" className="profile-choice" onClick={() => onPick(u.id)}>
                <Avatar color={u.color} name={u.name} />
                <span className="profile-name">{u.name}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
