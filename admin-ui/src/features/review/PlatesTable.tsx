import { useState } from "react";

import { editPrompt, editSelection } from "../../api/client";
import { ErrorNotice, Notice } from "../../components/common";
import type { Prompt, Selection } from "../../api/types";

type Plate = Selection["plates"][number];

// The plate table (§11.3): page id · reason · salience · beat · inline-editable prompt · include
// toggle, plus the cover/portrait pseudo-plates (prompt-editable only, no selection row). Thumb-less
// — this is the pre-render gate.
export function PlatesTable({
  bookId,
  selection,
  prompts,
  beats,
  promptWarnings,
  editable,
  onPromptSaved,
  onSelectionChanged,
}: {
  bookId: string;
  selection: Selection;
  prompts: Prompt[];
  beats: Record<string, string>;
  promptWarnings: Record<string, string[]>;
  editable: boolean;
  onPromptSaved: (p: Prompt) => void;
  onSelectionChanged: (s: Selection) => void;
}) {
  const promptByPage = new Map(prompts.map((p) => [p.page_id, p]));
  const pseudoPlates = prompts.filter((p) => !/^\d{4}$/.test(p.page_id));
  const plates = selection.plates.slice().sort((a, b) => a.page_id.localeCompare(b.page_id));

  const [addId, setAddId] = useState("");
  const [selError, setSelError] = useState<unknown>(null);

  async function toggle(plate: Plate, include: boolean) {
    setSelError(null);
    try {
      const updated = include
        ? await editSelection(bookId, { add: [plate.page_id] })
        : await editSelection(bookId, { remove: [plate.page_id] });
      onSelectionChanged(updated);
    } catch (err) {
      setSelError(err);
    }
  }

  async function addManual() {
    const id = addId.trim();
    if (!id) return;
    setSelError(null);
    try {
      const updated = await editSelection(bookId, { add: [id] });
      onSelectionChanged(updated);
      setAddId("");
    } catch (err) {
      setSelError(err);
    }
  }

  return (
    <div>
      <h3>Plates ({plates.length})</h3>
      <ErrorNotice error={selError} />
      <table>
        <thead>
          <tr>
            <th style={{ width: 34 }}>In</th>
            <th style={{ width: 54 }}>Page</th>
            <th style={{ width: 110 }}>Reason</th>
            <th style={{ width: 60 }}>Sal.</th>
            <th>Beat &amp; prompt</th>
          </tr>
        </thead>
        <tbody>
          {plates.map((plate) => (
            <PlateRow
              key={plate.page_id}
              bookId={bookId}
              plate={plate}
              prompt={promptByPage.get(plate.page_id)}
              beat={beats[plate.page_id]}
              warnings={promptWarnings[plate.page_id]}
              editable={editable}
              onToggle={toggle}
              onPromptSaved={onPromptSaved}
            />
          ))}
        </tbody>
      </table>

      {editable && (
        <div className="row" style={{ marginTop: 8 }}>
          <input
            type="text"
            aria-label="add page id"
            placeholder="0007"
            value={addId}
            onChange={(e) => setAddId(e.target.value)}
            style={{ width: 80 }}
          />
          <button onClick={addManual} disabled={!addId.trim()}>
            Add manual plate
          </button>
          <span className="muted">
            Manual plates get no prompt until a re-select re-runs derivation.
          </span>
        </div>
      )}

      {pseudoPlates.length > 0 && (
        <>
          <h3>Cover &amp; portraits</h3>
          <table>
            <thead>
              <tr>
                <th style={{ width: 200 }}>Plate</th>
                <th>Prompt</th>
              </tr>
            </thead>
            <tbody>
              {pseudoPlates.map((p) => (
                <PseudoRow
                  key={p.page_id}
                  bookId={bookId}
                  prompt={p}
                  editable={editable}
                  onPromptSaved={onPromptSaved}
                />
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}

function PromptEditor({
  bookId,
  prompt,
  editable,
  onPromptSaved,
}: {
  bookId: string;
  prompt: Prompt;
  editable: boolean;
  onPromptSaved: (p: Prompt) => void;
}) {
  const [draft, setDraft] = useState(prompt.final_subject_prompt);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const dirty = draft !== prompt.final_subject_prompt;
  const edited = prompt.edited_prompt !== null;

  async function save(value: string | null) {
    setBusy(true);
    setError(null);
    try {
      const updated = await editPrompt(bookId, prompt.page_id, value);
      onPromptSaved(updated);
      setDraft(updated.final_subject_prompt);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  if (!editable) {
    return (
      <div>
        <div className="mono" style={{ fontSize: 12.5 }}>{prompt.final_subject_prompt}</div>
        {edited && <span className="badge edited">edited</span>}
      </div>
    );
  }

  return (
    <div>
      <textarea rows={3} aria-label={`prompt ${prompt.page_id}`} value={draft} onChange={(e) => setDraft(e.target.value)} />
      <div className="row" style={{ marginTop: 4 }}>
        <button disabled={busy || !dirty} onClick={() => save(draft)}>
          {busy ? "Saving…" : "Save"}
        </button>
        {edited && (
          <button disabled={busy} onClick={() => save(null)} title="Revert to the derived prompt">
            Revert
          </button>
        )}
        {edited && <span className="badge edited">edited</span>}
      </div>
      <ErrorNotice error={error} />
    </div>
  );
}

function PlateRow({
  bookId,
  plate,
  prompt,
  beat,
  warnings,
  editable,
  onToggle,
  onPromptSaved,
}: {
  bookId: string;
  plate: Plate;
  prompt: Prompt | undefined;
  beat: string | undefined;
  warnings: string[] | undefined;
  editable: boolean;
  onToggle: (plate: Plate, include: boolean) => void;
  onPromptSaved: (p: Prompt) => void;
}) {
  const included = plate.status !== "retired";
  return (
    <tr>
      <td>
        <input
          type="checkbox"
          aria-label={`include ${plate.page_id}`}
          checked={included}
          disabled={!editable}
          onChange={(e) => onToggle(plate, e.target.checked)}
        />
      </td>
      <td className="mono">{plate.page_id}</td>
      <td>
        {plate.reason}
        {plate.status === "retired" && <div><span className="badge retired">retired</span></div>}
      </td>
      <td>{plate.salience.toFixed(2)}</td>
      <td>
        {beat && <div className="muted" style={{ marginBottom: 4 }}>{beat}</div>}
        {warnings && warnings.length > 0 && (
          <Notice kind="warn">{warnings.join("; ")}</Notice>
        )}
        {prompt ? (
          <PromptEditor bookId={bookId} prompt={prompt} editable={editable} onPromptSaved={onPromptSaved} />
        ) : (
          <span className="badge" style={{ color: "#a11414" }}>
            no prompt — needs re-derive
          </span>
        )}
      </td>
    </tr>
  );
}

function PseudoRow({
  bookId,
  prompt,
  editable,
  onPromptSaved,
}: {
  bookId: string;
  prompt: Prompt;
  editable: boolean;
  onPromptSaved: (p: Prompt) => void;
}) {
  return (
    <tr>
      <td className="mono">{prompt.page_id}</td>
      <td>
        <PromptEditor bookId={bookId} prompt={prompt} editable={editable} onPromptSaved={onPromptSaved} />
      </td>
    </tr>
  );
}
