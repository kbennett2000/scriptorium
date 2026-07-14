import type { HighlightColor } from "./segments";

// The floating action bar shown over a live text selection (DESIGN §13): four highlight colors, Note
// (highlight + text sheet), Copy. Positioned by the caller from the selection's bounding rect.
//
// Every control preventDefaults `mousedown` so clicking the bar does NOT collapse the selection before
// `onClick` runs — the standard rich-text-toolbar trick. The caller clears the selection after acting.

const COLORS: HighlightColor[] = ["yellow", "blue", "green", "pink"];

// Enough vertical room for the bar to sit ABOVE the selection; below this it flips underneath so it
// never renders off the top of the viewport (a selection near the top of the page).
const BAR_CLEARANCE_PX = 56;

export function SelectionBar({
  rect,
  onColor,
  onNote,
  onCopy,
}: {
  rect: { top: number; bottom: number; left: number; width: number };
  onColor: (color: HighlightColor) => void;
  onNote: () => void;
  onCopy: () => void;
}) {
  const keepSelection = (e: React.MouseEvent) => e.preventDefault();
  const below = rect.top < BAR_CLEARANCE_PX;
  return (
    <div
      className={`sel-bar${below ? " sel-bar--below" : ""}`}
      role="toolbar"
      aria-label="Selection actions"
      style={{ top: below ? rect.bottom : rect.top, left: rect.left + rect.width / 2 }}
      onMouseDown={keepSelection}
    >
      {COLORS.map((c) => (
        <button
          key={c}
          type="button"
          className={`sel-swatch hl-${c}`}
          aria-label={`Highlight ${c}`}
          onMouseDown={keepSelection}
          onClick={() => onColor(c)}
        />
      ))}
      <button type="button" className="sel-action" onMouseDown={keepSelection} onClick={onNote}>
        Note
      </button>
      <button type="button" className="sel-action" onMouseDown={keepSelection} onClick={onCopy}>
        Copy
      </button>
    </div>
  );
}
