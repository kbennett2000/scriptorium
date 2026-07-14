import { useState } from "react";

// A small sheet for a note's body text (DESIGN §13: "Note = highlight + text sheet"). Used both when
// creating a note from a selection and when editing an existing note's text. The highlight itself is
// created/updated by the caller; this only collects the text.

export function NoteSheet({
  initial,
  onSave,
  onCancel,
}: {
  initial: string;
  onSave: (text: string) => void;
  onCancel: () => void;
}) {
  const [text, setText] = useState(initial);
  return (
    <div className="note-sheet" role="dialog" aria-label="Note">
      <textarea
        className="note-input"
        value={text}
        placeholder="Add a note…"
        autoFocus
        onChange={(e) => setText(e.target.value)}
      />
      <div className="note-actions">
        <button type="button" onClick={onCancel}>
          Cancel
        </button>
        <button type="button" onClick={() => onSave(text)} disabled={!text.trim()}>
          Save
        </button>
      </div>
    </div>
  );
}
