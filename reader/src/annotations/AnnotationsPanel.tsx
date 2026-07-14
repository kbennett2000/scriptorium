import { useState } from "react";

import type { Annotation } from "./store";

// The per-book annotations list (DESIGN §13): filter by type and color; tap a row to jump to its page
// (+ flash); delete a row (tombstone). An in-Reader overlay, not a route — the reader stays a single
// mounted surface. `items` is the LIVE (non-tombstoned) set, already page-agnostic.

const TYPES = ["all", "highlight", "note", "bookmark"] as const;
const COLORS = ["all", "yellow", "blue", "green", "pink"] as const;
type TypeFilter = (typeof TYPES)[number];
type ColorFilter = (typeof COLORS)[number];

export function AnnotationsPanel({
  items,
  onJump,
  onDelete,
  onClose,
}: {
  items: Annotation[];
  onJump: (annotation: Annotation) => void;
  onDelete: (id: string) => void;
  onClose: () => void;
}) {
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  const [colorFilter, setColorFilter] = useState<ColorFilter>("all");

  const filtered = items.filter(
    (a) =>
      (typeFilter === "all" || a.type === typeFilter) &&
      (colorFilter === "all" || a.color === colorFilter),
  );

  return (
    <div className="ann-panel" role="dialog" aria-label="Annotations">
      <div className="ann-panel-head">
        <strong>Annotations</strong>
        <button type="button" className="ann-close" aria-label="Close annotations" onClick={onClose}>
          ×
        </button>
      </div>
      <div className="ann-filters">
        <label>
          Type{" "}
          <select
            aria-label="Filter by type"
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value as TypeFilter)}
          >
            {TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <label>
          Color{" "}
          <select
            aria-label="Filter by color"
            value={colorFilter}
            onChange={(e) => setColorFilter(e.target.value as ColorFilter)}
          >
            {COLORS.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
      </div>
      <ul className="ann-list">
        {filtered.length === 0 && <li className="ann-empty">No annotations yet.</li>}
        {filtered.map((a) => (
          <li key={a.id} className="ann-row">
            <button type="button" className="ann-jump" onClick={() => onJump(a)}>
              <span className={`ann-badge ann-${a.type}${a.color ? ` hl-${a.color}` : ""}`}>
                {a.type}
              </span>
              <span className="ann-loc">p.{a.page_id}</span>
              {a.text && <span className="ann-text">{a.text}</span>}
            </button>
            <button
              type="button"
              className="ann-del"
              aria-label="Delete annotation"
              onClick={() => onDelete(a.id)}
            >
              Delete
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
