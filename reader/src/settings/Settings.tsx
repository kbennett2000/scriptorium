import { useEffect, useState } from "react";

import { ProfilePicker } from "../profiles";
import type { Storage } from "../shell";
import type { SyncClient, SyncStatus } from "../sync";
import { SyncStatusBadge } from "../sync";

// A minimal Settings surface (DESIGN §13). The full designed screen (font size, theme, typeface) is
// R4 — this stub carries only R3's concerns: the active profile + switcher, a manual Sync now button,
// last-synced + storage status. Profile switching just changes the active profile (no migration —
// that is a one-time first-run step); each profile's data is already namespaced.

export function Settings({
  user,
  users,
  client,
  storage,
  status,
  onPickProfile,
  onClose,
}: {
  user: string;
  users: { id: string; name: string }[];
  client: SyncClient;
  storage: Storage;
  status: SyncStatus;
  onPickProfile: (id: string) => void;
  onClose: () => void;
}) {
  const [switching, setSwitching] = useState(false);
  const [persisted, setPersisted] = useState<boolean | null>(null);
  const activeName = users.find((u) => u.id === user)?.name ?? user;

  useEffect(() => {
    if (!navigator.storage?.persisted) return;
    void navigator.storage.persisted().then(setPersisted);
  }, []);

  if (switching) {
    return (
      <section className="settings">
        <ProfilePicker
          client={client}
          storage={storage}
          heading="Switch profile"
          onPick={(id) => {
            setSwitching(false);
            onPickProfile(id);
          }}
        />
        <button type="button" onClick={() => setSwitching(false)}>
          Cancel
        </button>
      </section>
    );
  }

  return (
    <section className="settings">
      <div className="settings-bar">
        <h2>Settings</h2>
        <button type="button" onClick={onClose}>
          Done
        </button>
      </div>

      <div className="settings-row">
        <span className="settings-label">Profile</span>
        <span className="settings-value">{activeName}</span>
        <button type="button" onClick={() => setSwitching(true)}>
          Switch profile
        </button>
      </div>

      <div className="settings-row">
        <span className="settings-label">Sync</span>
        <SyncStatusBadge status={status} />
        <button type="button" className="settings-sync" onClick={() => void status.syncNow(true)}>
          Sync now
        </button>
      </div>

      <div className="settings-row">
        <span className="settings-label">Storage</span>
        <span className="settings-value">
          {persisted === null ? "unknown" : persisted ? "protected" : "not protected"}
        </span>
      </div>
    </section>
  );
}
