import type { ArtsetList } from "@scriptorium/shared";

// The reader's "Pictures" menu (DESIGN §8, ADR-0014): choose which set of illustrations to view for
// this book. Every book starts on "Default" (the shipped art). It's a full-screen overlay — NOT a
// page injected into the reading order — so positions/anchors and the byte-stable pagination are
// untouched; a set only changes which images the reading surface shows. Fully offline. Creating and
// deleting personal sets arrive in later cycles; this is the switcher.

type SetSummary = ArtsetList["sets"][number];

export function SetPicker({
  sets,
  activeSetId,
  onChoose,
  onClose,
}: {
  sets: SetSummary[];
  activeSetId: string;
  onChoose: (setId: string) => void;
  onClose: () => void;
}) {
  return (
    <section className="setpicker" role="dialog" aria-label="Pictures">
      <div className="setpicker-bar">
        <h2>Pictures</h2>
        <button type="button" onClick={onClose}>
          Done
        </button>
      </div>
      <ul className="setpicker-list">
        {sets.map((s) => {
          const active = s.set_id === activeSetId;
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
                onClick={() => onChoose(s.set_id)}
              >
                <span className="setpicker-label">{s.label}</span>
                {active && (
                  <span className="setpicker-inuse" aria-label="In use">
                    ✓ In use
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
