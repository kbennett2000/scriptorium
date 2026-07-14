import { useState } from "react";

import { editCast } from "../../api/client";
import { ErrorNotice } from "../../components/common";
import type { Cast } from "../../api/types";

type Character = Cast["characters"][number];

// The cast side panel (§11.3): editable visual_description + one_line per character. Saving flips
// the server-side edited_by_human flag (§4.3), surfaced here as a badge.
export function CastPanel({
  bookId,
  cast,
  editable,
  onCastSaved,
}: {
  bookId: string;
  cast: Cast;
  editable: boolean;
  onCastSaved: (c: Character) => void;
}) {
  return (
    <div className="panel">
      <h3 style={{ marginTop: 0 }}>Cast ({cast.characters.length})</h3>
      {cast.characters.length === 0 && <p className="muted">No characters.</p>}
      {cast.characters.map((c) => (
        <CastCard
          key={c.slug}
          bookId={bookId}
          character={c}
          editable={editable}
          onSaved={onCastSaved}
        />
      ))}
    </div>
  );
}

function CastCard({
  bookId,
  character,
  editable,
  onSaved,
}: {
  bookId: string;
  character: Character;
  editable: boolean;
  onSaved: (c: Character) => void;
}) {
  const [desc, setDesc] = useState(character.visual_description ?? "");
  const [oneLine, setOneLine] = useState(character.one_line);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const dirty = desc !== (character.visual_description ?? "") || oneLine !== character.one_line;

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const updated = await editCast(bookId, character.slug, {
        visual_description: desc,
        one_line: oneLine,
      });
      onSaved(updated);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="cast-card">
      <div className="spread">
        <strong>{character.name}</strong>
        <span>
          <span className="badge">{character.major ? "major" : "minor"}</span>{" "}
          {character.edited_by_human && <span className="badge edited">edited</span>}
        </span>
      </div>
      <div className="muted mono" style={{ fontSize: 11 }}>{character.slug}</div>

      {editable ? (
        <>
          <label style={{ display: "block", marginTop: 6 }}>
            <span className="muted">One-line</span>
            <input
              type="text"
              value={oneLine}
              onChange={(e) => setOneLine(e.target.value)}
              style={{ width: "100%" }}
            />
          </label>
          <label style={{ display: "block", marginTop: 6 }}>
            <span className="muted">Visual description</span>
            <textarea rows={3} value={desc} onChange={(e) => setDesc(e.target.value)} />
          </label>
          <div className="row" style={{ marginTop: 4 }}>
            <button disabled={busy || !dirty} onClick={save}>
              {busy ? "Saving…" : "Save"}
            </button>
          </div>
          <ErrorNotice error={error} />
        </>
      ) : (
        <>
          <p style={{ margin: "6px 0 2px" }}>{character.one_line}</p>
          {character.visual_description && (
            <p className="muted" style={{ margin: 0 }}>{character.visual_description}</p>
          )}
        </>
      )}
    </div>
  );
}
