import { useState } from "react";

import type { SetRow } from "./useArtsets";
import type { StyleOption } from "../shelf";
import { DEFAULT_SET_ID } from "./activeSet";

// The reader's "Pictures" menu (DESIGN §8, ADR-0014): choose which set of illustrations to view for
// this book, and make/delete your own private sets. Every book starts on "Default" (the shipped art).
// It's a full-screen overlay — NOT a page injected into the reading order — so positions/anchors and the
// byte-stable pagination are untouched; a set only changes which images the reading surface shows.
// Presentational: all data + actions come from useArtsets. Reading a resident set is fully offline;
// making/downloading/deleting need the home server (disabled + explained when it's unreachable).

function primaryLabel(row: SetRow, active: boolean): string {
  if (active) return "✓ In use";
  if (row.status === "generating") {
    const p = row.render_progress;
    // The live count makes "making pictures" visibly move; plain text when the server hasn't sent one
    // yet (or we're offline on a cached list).
    return p && p.total > 0 ? `Making your pictures… ${p.done} of ${p.total}` : "Making your pictures…";
  }
  if (row.status === "failed") return "Couldn’t make this one";
  if (row.residency === "resident") return "Use";
  return "Download & use";
}

export function SetPicker({
  sets,
  styles,
  models,
  activeSetId,
  online,
  busy,
  error,
  onChoose,
  onCreate,
  onDelete,
  onRetry,
  onClose,
}: {
  sets: SetRow[];
  styles: StyleOption[];
  models: string[];
  activeSetId: string;
  online: boolean;
  busy: boolean;
  error: string | null;
  onChoose: (setId: string) => void;
  onCreate: (kind: "style" | "reroll", styleId?: string, model?: string | null) => void;
  onDelete: (setId: string) => void;
  onRetry: (setId: string) => void;
  onClose: () => void;
}) {
  const [adding, setAdding] = useState(false);
  // "" → omit the model so the home server picks its default image engine (ADR-0030).
  const [model, setModel] = useState<string>("");
  const chosenModel = model || undefined;

  return (
    <section className="setpicker" role="dialog" aria-label="Pictures">
      <div className="setpicker-bar">
        <h2>Pictures</h2>
        <button type="button" onClick={onClose}>
          Done
        </button>
      </div>

      {!online && (
        <p className="setpicker-note">
          Connect to your home server to make or download picture sets. Sets already on this device
          still work.
        </p>
      )}
      {error && <p className="setpicker-error">{error}</p>}

      <ul className="setpicker-list">
        {sets.map((s) => {
          const active = s.set_id === activeSetId;
          const chooseable = active || s.status === "ready";
          return (
            <li
              key={s.set_id}
              className={`setpicker-entry${active ? " active" : ""}`}
              data-set-id={s.set_id}
            >
              <button
                type="button"
                className="setpicker-choose"
                aria-pressed={active}
                disabled={!chooseable || busy}
                onClick={() => onChoose(s.set_id)}
              >
                <span className="setpicker-label">{s.label}</span>
                <span className="setpicker-action">{primaryLabel(s, active)}</span>
              </button>
              {s.status === "generating" && s.render_progress && s.render_progress.total > 0 && (
                <progress
                  className="setpicker-genbar"
                  aria-label={`Making ${s.label}`}
                  max={s.render_progress.total}
                  value={s.render_progress.done}
                />
              )}
              {s.progress && (
                <span className="setpicker-progress" aria-live="polite">
                  Downloading… {s.progress.done}/{s.progress.total}
                </span>
              )}
              {s.status === "failed" && (
                <button
                  type="button"
                  className="setpicker-retry"
                  aria-label={`Retry ${s.label}`}
                  disabled={!online || busy}
                  onClick={() => onRetry(s.set_id)}
                >
                  Retry
                </button>
              )}
              {s.set_id !== DEFAULT_SET_ID && (
                <button
                  type="button"
                  className="setpicker-delete"
                  aria-label={`Delete ${s.label}`}
                  disabled={!online || busy}
                  onClick={() => onDelete(s.set_id)}
                >
                  Delete
                </button>
              )}
            </li>
          );
        })}
      </ul>

      {online &&
        (adding ? (
          <div className="setpicker-new" role="group" aria-label="New picture set">
            <p className="setpicker-new-title">Pick a look for a new set:</p>
            {models.length > 0 && (
              <label className="setpicker-model">
                Image engine
                <select value={model} onChange={(e) => setModel(e.target.value)} disabled={busy}>
                  <option value="">Automatic</option>
                  {models.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <button
              type="button"
              className="setpicker-style"
              disabled={busy}
              onClick={() => {
                onCreate("reroll", undefined, chosenModel);
                setAdding(false);
              }}
            >
              Same style, fresh pictures
            </button>
            {styles.map((st) => (
              <button
                key={st.id}
                type="button"
                className="setpicker-style"
                disabled={busy}
                onClick={() => {
                  onCreate("style", st.id, chosenModel);
                  setAdding(false);
                }}
              >
                {st.name}
              </button>
            ))}
            <button type="button" className="setpicker-cancel" onClick={() => setAdding(false)}>
              Cancel
            </button>
          </div>
        ) : (
          <button
            type="button"
            className="setpicker-add"
            disabled={busy}
            onClick={() => setAdding(true)}
          >
            ＋ New set
          </button>
        ))}
    </section>
  );
}
