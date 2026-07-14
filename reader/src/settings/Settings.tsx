import { useEffect, useState } from "react";

import { ProfilePicker } from "../profiles";
import type { Storage } from "../shell";
import type { SyncClient, SyncStatus } from "../sync";
import { SyncStatusBadge } from "../sync";
import { FONT_STEPS, type Prefs, type Theme, type Typeface } from "./prefs";

// The full Settings screen (DESIGN §13): reading display (typeface, font size, theme) + the R3 concerns
// (profile switcher, manual sync + last-synced, storage status). Display prefs apply instantly via the
// App-level usePrefs controller (persisted per device); profile switching just repoints the active
// profile (no migration — that is a one-time first-run step). Everything here is local.

const THEME_LABELS: Record<Theme, string> = { light: "Light", sepia: "Sepia", dark: "Dark" };
const TYPEFACE_LABELS: Record<Typeface, string> = { literata: "Literata", inter: "Inter" };

export function Settings({
  user,
  users,
  client,
  storage,
  status,
  prefs,
  onUpdatePrefs,
  onPickProfile,
  onClose,
}: {
  user: string;
  users: { id: string; name: string }[];
  client: SyncClient;
  storage: Storage;
  status: SyncStatus;
  prefs: Prefs;
  onUpdatePrefs: (patch: Partial<Prefs>) => void;
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
        <span className="settings-label">Typeface</span>
        <div className="settings-choices">
          {(["literata", "inter"] as Typeface[]).map((t) => (
            <button
              key={t}
              type="button"
              className="settings-choice"
              aria-pressed={prefs.typeface === t}
              onClick={() => onUpdatePrefs({ typeface: t })}
            >
              {TYPEFACE_LABELS[t]}
            </button>
          ))}
        </div>
      </div>

      <div className="settings-row">
        <span className="settings-label">Font size</span>
        <div className="settings-fontsize">
          <button
            type="button"
            aria-label="Smaller text"
            disabled={prefs.fontStep <= 0}
            onClick={() => onUpdatePrefs({ fontStep: prefs.fontStep - 1 })}
          >
            A−
          </button>
          <span className="settings-value" aria-label="Font size step">
            {prefs.fontStep + 1} / {FONT_STEPS}
          </span>
          <button
            type="button"
            aria-label="Larger text"
            disabled={prefs.fontStep >= FONT_STEPS - 1}
            onClick={() => onUpdatePrefs({ fontStep: prefs.fontStep + 1 })}
          >
            A+
          </button>
        </div>
      </div>

      <div className="settings-row">
        <span className="settings-label">Theme</span>
        <div className="settings-choices">
          {(["light", "sepia", "dark"] as Theme[]).map((t) => (
            <button
              key={t}
              type="button"
              className="settings-choice"
              aria-pressed={prefs.theme === t}
              onClick={() => onUpdatePrefs({ theme: t })}
            >
              {THEME_LABELS[t]}
            </button>
          ))}
        </div>
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
