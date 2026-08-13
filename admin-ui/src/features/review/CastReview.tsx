import { useState } from "react";

import { approveCast, getReview, isCastApproveError } from "../../api/client";
import { ErrorNotice, Loading, Notice, useAsync } from "../../components/common";
import type { Cast, CastApproveError, ReviewPayload } from "../../api/types";
import { navigate } from "../../routes";
import { CastPanel } from "./CastPanel";

// Only the gate itself is editable; once approved the cast is shown read-only.
const EDITABLE_STATES = ["cast_done"];

// The cast-review gate (ADR-0032): the first stop, before any scene prompts are derived. The owner
// reviews/edits each character here so the scene prompts (P5) are generated from the approved
// descriptions — saving the re-editing that used to happen at the later prompt gate. Reuses the same
// review payload + CastPanel + editCast mutation as the prompt gate; only the approve call differs.
export function CastReview({ id }: { id: string }) {
  const { data, error, loading } = useAsync(() => getReview(id), [id]);
  return (
    <section>
      <div className="crumbs">
        <a onClick={() => navigate({ name: "list" })}>Books</a> ›{" "}
        <a onClick={() => navigate({ name: "detail", id })}>{id}</a> › Cast review
      </div>
      {loading && <Loading what="cast" />}
      <ErrorNotice error={error} prefix="Could not load cast" />
      {data && <CastReviewBody id={id} initial={data} />}
    </section>
  );
}

function CastReviewBody({ id, initial }: { id: string; initial: ReviewPayload }) {
  const [review, setReview] = useState<ReviewPayload>(initial);
  const editable = EDITABLE_STATES.includes(review.state);

  const patchCharacter = (c: Cast["characters"][number]) =>
    setReview((r) => ({
      ...r,
      cast: { characters: r.cast.characters.map((old) => (old.slug === c.slug ? c : old)) },
    }));

  return (
    <>
      <div className="spread">
        <h2>Cast review — {review.book_id}</h2>
        <span className="badge state">{review.state}</span>
      </div>

      <p className="muted" style={{ marginTop: 0 }}>
        Review each character before the scene descriptions are generated. Approving derives the
        scene prompts from these descriptions, then stops again at the plate review.
      </p>

      {!editable && (
        <Notice kind="warn">
          This book is <code>{review.state}</code>; the cast is read-only (editable only at the
          cast gate).
        </Notice>
      )}

      <CastPanel bookId={id} cast={review.cast} editable={editable} onCastSaved={patchCharacter} />

      {editable && <ApproveCastBar bookId={id} cast={review.cast} />}
    </>
  );
}

// Approve gate: locks in the descriptions and lets derivation run. A 422 refusal names any major
// still missing a description (mirrors the prompt gate's missing-prompt refusal).
function ApproveCastBar({ bookId, cast }: { bookId: string; cast: Cast }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<CastApproveError | null>(null);
  const [error, setError] = useState<unknown>(null);

  const majors = cast.characters.filter((c) => c.major).length;

  async function doApprove() {
    setBusy(true);
    setRefusal(null);
    setError(null);
    try {
      await approveCast(bookId);
      navigate({ name: "detail", id: bookId });
    } catch (err) {
      if (
        err &&
        typeof err === "object" &&
        "detail" in err &&
        isCastApproveError((err as { detail: unknown }).detail)
      ) {
        setRefusal((err as { detail: CastApproveError }).detail);
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
        <h3 style={{ margin: 0 }}>Approve cast</h3>
        <button className="primary" onClick={() => setConfirming(true)}>
          Approve…
        </button>
      </div>
      {refusal && (
        <Notice kind="error">
          Cannot approve — {refusal.slugs.length} major character(s) still lack a description:{" "}
          <span className="mono">{refusal.slugs.join(", ")}</span>. Fill those in first.
        </Notice>
      )}
      <ErrorNotice error={error} prefix="Approve failed" />

      {confirming && (
        <div className="dialog-backdrop" onClick={() => !busy && setConfirming(false)}>
          <div className="dialog" onClick={(e) => e.stopPropagation()}>
            <h3 style={{ marginTop: 0 }}>Approve these descriptions?</h3>
            <p>
              The scene descriptions will be generated from{" "}
              <strong>{majors}</strong> approved character(s). You will review the generated scene
              prompts at the next gate.
            </p>
            <div className="row" style={{ justifyContent: "flex-end" }}>
              <button disabled={busy} onClick={() => setConfirming(false)}>
                Cancel
              </button>
              <button className="primary" disabled={busy} onClick={doApprove}>
                {busy ? "Approving…" : "Approve cast"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
