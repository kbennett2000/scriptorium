import { useState } from "react";

import { approve, getReview, isApproveError, reselect } from "../../api/client";
import { ErrorNotice, Loading, Notice, useAsync } from "../../components/common";
import type {
  ApproveError,
  Cast,
  DensityPreset,
  Prompt,
  ReviewPayload,
  Selection,
} from "../../api/types";
import { navigate } from "../../routes";
import { CastPanel } from "./CastPanel";
import { PlatesTable } from "./PlatesTable";

const EDITABLE_STATES = ["prompts_draft", "in_review"];

// The review gate (§11.3, "the heart"): the plate table + cast panel + the Approve gate. Holds a
// local copy of the payload and patches it from each mutation's response so inline edits keep focus
// without a full reload.
export function ReviewGate({ id }: { id: string }) {
  const { data, error, loading } = useAsync(() => getReview(id), [id]);
  return (
    <section>
      <div className="crumbs">
        <a onClick={() => navigate({ name: "list" })}>Books</a> ›{" "}
        <a onClick={() => navigate({ name: "detail", id })}>{id}</a> › Review
      </div>
      {loading && <Loading what="review" />}
      <ErrorNotice error={error} prefix="Could not load review" />
      {data && <ReviewBody id={id} initial={data} />}
    </section>
  );
}

function ReviewBody({ id, initial }: { id: string; initial: ReviewPayload }) {
  const [review, setReview] = useState<ReviewPayload>(initial);
  const editable = EDITABLE_STATES.includes(review.state);

  const patchPrompt = (p: Prompt) =>
    setReview((r) => ({
      ...r,
      prompts: r.prompts.map((old) => (old.page_id === p.page_id ? p : old)),
    }));
  const patchSelection = (s: Selection) => setReview((r) => ({ ...r, selection: s }));
  const patchCharacter = (c: Cast["characters"][number]) =>
    setReview((r) => ({
      ...r,
      cast: { characters: r.cast.characters.map((old) => (old.slug === c.slug ? c : old)) },
    }));

  return (
    <>
      <div className="spread">
        <h2>Review — {review.book_id}</h2>
        <span className="badge state">{review.state}</span>
      </div>

      {!editable && (
        <Notice kind="warn">
          This book is <code>{review.state}</code>; prompts, selection and cast are read-only
          (edits are pre-approval only).
        </Notice>
      )}

      <div className="review-grid">
        <div>
          <PlatesTable
            bookId={id}
            selection={review.selection}
            prompts={review.prompts}
            beats={review.beats}
            promptWarnings={review.prompt_warnings}
            editable={editable}
            onPromptSaved={patchPrompt}
            onSelectionChanged={patchSelection}
          />
        </div>
        <aside>
          <CastPanel
            bookId={id}
            cast={review.cast}
            editable={editable}
            onCastSaved={patchCharacter}
          />
          {editable && (
            <ReselectControl
              bookId={id}
              current={review.selection.preset}
            />
          )}
        </aside>
      </div>

      {editable && (
        <ApproveBar bookId={id} selection={review.selection} promptIds={review.prompts.map((p) => p.page_id)} />
      )}
    </>
  );
}

// Density re-turn (§8). Reselect re-queues P5 for newcomers (server resets state → selected), so it
// leaves the review; we send the operator back to the detail screen to watch derivation.
function ReselectControl({ bookId, current }: { bookId: string; current: DensityPreset }) {
  const [preset, setPreset] = useState<DensityPreset>(current);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      await reselect(bookId, preset);
      navigate({ name: "detail", id: bookId });
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <div className="panel">
      <h3 style={{ marginTop: 0 }}>Re-turn density</h3>
      <p className="muted" style={{ marginTop: 0 }}>
        Re-selects plates at a new density and re-runs prompt derivation for any newcomers. Returns
        to the book while it re-derives.
      </p>
      <div className="row">
        <select value={preset} onChange={(e) => setPreset(e.target.value as DensityPreset)}>
          <option value="lavish">lavish</option>
          <option value="classic">classic</option>
          <option value="sparse">sparse</option>
        </select>
        <button disabled={busy || preset === current} onClick={run}>
          {busy ? "Re-selecting…" : "Re-select"}
        </button>
      </div>
      <ErrorNotice error={error} />
    </div>
  );
}

// Approve gate: confirmation shows the renderable plate count; a 422 refusal names the promptless
// pages (invariant #4 made real — no render before a complete, approved shot list).
function ApproveBar({
  bookId,
  selection,
  promptIds,
}: {
  bookId: string;
  selection: Selection;
  promptIds: string[];
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<ApproveError | null>(null);
  const [error, setError] = useState<unknown>(null);

  const renderable = selection.plates.filter(
    (p) => p.status === "selected" || p.status === "approved" || p.reason === "manual",
  );
  const pseudo = promptIds.filter((pid) => !/^\d{4}$/.test(pid));

  async function doApprove() {
    setBusy(true);
    setRefusal(null);
    setError(null);
    try {
      await approve(bookId);
      navigate({ name: "detail", id: bookId });
    } catch (err) {
      if (err && typeof err === "object" && "detail" in err && isApproveError((err as { detail: unknown }).detail)) {
        setRefusal((err as { detail: ApproveError }).detail);
      } else {
        setError(err);
      }
      setBusy(false);
      setConfirming(false);
    }
  }

  return (
    <div className="panel" style={{ marginTop: 16 }}>
      <div className="spread">
        <h3 style={{ margin: 0 }}>Approve shot list</h3>
        <button className="primary" onClick={() => setConfirming(true)}>
          Approve…
        </button>
      </div>
      {refusal && (
        <Notice kind="error">
          Cannot approve — {refusal.page_ids.length} plate(s) still lack a prompt:{" "}
          <span className="mono">{refusal.page_ids.join(", ")}</span>. Derive prompts (re-select) or
          remove those plates first.
        </Notice>
      )}
      <ErrorNotice error={error} prefix="Approve failed" />

      {confirming && (
        <div className="dialog-backdrop" onClick={() => !busy && setConfirming(false)}>
          <div className="dialog" onClick={(e) => e.stopPropagation()}>
            <h3 style={{ marginTop: 0 }}>Approve this shot list?</h3>
            <p>
              <strong>{renderable.length}</strong> page plate(s)
              {pseudo.length > 0 && (
                <>
                  {" "}plus <strong>{pseudo.length}</strong> pseudo-plate(s) ({pseudo.join(", ")})
                </>
              )}{" "}
              will be locked and queued for render. This cannot be edited afterwards.
            </p>
            <div className="row" style={{ justifyContent: "flex-end" }}>
              <button disabled={busy} onClick={() => setConfirming(false)}>
                Cancel
              </button>
              <button className="primary" disabled={busy} onClick={doApprove}>
                {busy ? "Approving…" : `Approve ${renderable.length} plates`}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
