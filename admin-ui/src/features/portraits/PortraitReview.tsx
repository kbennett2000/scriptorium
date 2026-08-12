import { useEffect, useState } from "react";

import {
  approvePortraits,
  editCast,
  editPrompt,
  getReview,
  plateImageUrl,
  regenPlate,
} from "../../api/client";
import { ErrorNotice, errorText, Loading, Notice, useAsync } from "../../components/common";
import type { Cast, Prompt, ReviewPayload } from "../../api/types";
import { navigate } from "../../routes";

// Optional portrait-review gate (ADR-0025). While a book rests at `portraits_review`, the owner
// sees every character portrait next to the prompt that drew it, can edit the prompt OR the
// character's description, and re-generate that single portrait until happy — then approves, and the
// book draws the rest of its pages seeded by the now-approved portraits.
const PORTRAIT_PREFIX = "portrait-";

export function PortraitReview({ id }: { id: string }) {
  const { data, error, loading, reload } = useAsync(() => getReview(id), [id]);

  // Poll while the portraits are still rendering so the grid appears on its own when they land.
  useEffect(() => {
    if (data?.state !== "portraits_rendering") return;
    const t = setInterval(reload, 3500);
    return () => clearInterval(t);
  }, [data?.state, reload]);

  return (
    <section>
      <Crumbs id={id} />
      {loading && <Loading what="portraits" />}
      <ErrorNotice error={error} prefix="Could not load portraits" />
      {data && <PortraitReviewBody id={id} review={data} reload={reload} />}
    </section>
  );
}

function Crumbs({ id }: { id: string }) {
  return (
    <div className="crumbs">
      <a onClick={() => navigate({ name: "list" })}>Books</a> ›{" "}
      <a onClick={() => navigate({ name: "detail", id })}>{id}</a> › Portraits
    </div>
  );
}

function PortraitReviewBody({
  id,
  review,
  reload,
}: {
  id: string;
  review: ReviewPayload;
  reload: () => void;
}) {
  const portraits = review.prompts.filter((p) => p.page_id.startsWith(PORTRAIT_PREFIX));
  const castBySlug = new Map(review.cast.characters.map((c) => [c.slug, c]));

  const atGate = review.state === "portraits_review";
  const stillRendering = review.state === "portraits_rendering";

  const [approving, setApproving] = useState(false);
  const [approveError, setApproveError] = useState<unknown>(null);

  async function approveAll() {
    setApproving(true);
    setApproveError(null);
    try {
      await approvePortraits(id);
      navigate({ name: "detail", id });
    } catch (err) {
      setApproveError(err);
      setApproving(false);
    }
  }

  return (
    <>
      <div className="spread">
        <h2>Portrait review — {review.book_id}</h2>
        <span className="badge state">{review.state}</span>
      </div>

      {stillRendering && (
        <Notice kind="ok">
          The portraits are still being drawn — this page will fill in as they finish.
        </Notice>
      )}
      {!atGate && !stillRendering && (
        <Notice kind="warn">
          These portraits are already approved (the book has moved on). Editing is closed.
        </Notice>
      )}
      {review.render_stub && (
        <Notice kind="warn">
          These are <strong>placeholder</strong> renders from the demo stub, not final art.
        </Notice>
      )}
      {portraits.length === 0 && !stillRendering && (
        <Notice kind="ok">This book has no character portraits to review.</Notice>
      )}

      <div className="portrait-grid">
        {portraits.map((prompt) => (
          <PortraitCard
            key={prompt.page_id}
            id={id}
            prompt={prompt}
            character={castBySlug.get(prompt.page_id.slice(PORTRAIT_PREFIX.length)) ?? null}
            editable={atGate}
            reload={reload}
          />
        ))}
      </div>

      {atGate && (
        <div className="row" style={{ marginTop: 16 }}>
          <button className="primary" disabled={approving} onClick={approveAll}>
            {approving ? "Approving…" : "Approve portraits & draw the book"}
          </button>
          {approveError != null && (
            <Notice kind="error">Approve failed: {errorText(approveError)}</Notice>
          )}
        </div>
      )}
    </>
  );
}

function PortraitCard({
  id,
  prompt,
  character,
  editable,
  reload,
}: {
  id: string;
  prompt: Prompt;
  character: Cast["characters"][number] | null;
  editable: boolean;
  reload: () => void;
}) {
  const [promptDraft, setPromptDraft] = useState(prompt.final_subject_prompt);
  const [descDraft, setDescDraft] = useState(character?.visual_description ?? "");
  const [busy, setBusy] = useState<null | "prompt" | "revert" | "desc" | "regen">(null);
  const [error, setError] = useState<unknown>(null);
  // Cache-bust the image after a regenerate (same URL, new bytes).
  const [bump, setBump] = useState(0);
  // Click-to-zoom lightbox for this portrait (the tile is small).
  const [zoomed, setZoomed] = useState(false);

  const src = `${plateImageUrl(id, prompt.page_id)}?v=${bump}`;
  const label = character?.name ?? prompt.page_id;

  // Close the lightbox on Escape while it is open.
  useEffect(() => {
    if (!zoomed) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setZoomed(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [zoomed]);

  const promptDirty = promptDraft !== prompt.final_subject_prompt;
  const edited = prompt.edited_prompt !== null;
  const descDirty = descDraft !== (character?.visual_description ?? "");

  // Keep the drafts in sync when the server value changes (after a save/revert/regen reload, incl.
  // a description edit re-deriving the prompt). Reloads only happen after explicit actions here, so
  // this never clobbers an in-progress edit.
  useEffect(() => setPromptDraft(prompt.final_subject_prompt), [prompt.final_subject_prompt]);
  useEffect(
    () => setDescDraft(character?.visual_description ?? ""),
    [character?.visual_description],
  );

  async function run(kind: "prompt" | "revert" | "desc" | "regen", fn: () => Promise<unknown>) {
    setBusy(kind);
    setError(null);
    try {
      await fn();
      reload();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="portrait-card">
      <img
        className="portrait-img"
        src={src}
        alt={label}
        loading="lazy"
        title="Click to enlarge"
        onClick={() => setZoomed(true)}
      />
      {zoomed && (
        <div className="lightbox" onClick={() => setZoomed(false)} role="dialog" aria-label={label}>
          <img className="lightbox-img" src={src} alt={label} />
        </div>
      )}
      <div className="portrait-meta">
        <div className="portrait-name">{character?.name ?? prompt.page_id}</div>

        <label className="portrait-label">
          Picture instructions {edited && <span className="badge edited">edited</span>}
        </label>
        <textarea
          rows={3}
          aria-label={`prompt ${prompt.page_id}`}
          value={promptDraft}
          disabled={!editable}
          onChange={(e) => setPromptDraft(e.target.value)}
        />
        {editable && (
          <div className="row">
            <button
              disabled={busy !== null || !promptDirty}
              onClick={() => run("prompt", () => editPrompt(id, prompt.page_id, promptDraft))}
            >
              {busy === "prompt" ? "Saving…" : "Save prompt"}
            </button>
            {edited && (
              <button
                disabled={busy !== null}
                title="Revert to the description-derived prompt"
                onClick={() =>
                  run("revert", async () => {
                    const updated = await editPrompt(id, prompt.page_id, null);
                    setPromptDraft(updated.final_subject_prompt);
                  })
                }
              >
                Revert
              </button>
            )}
          </div>
        )}

        {character && (
          <>
            <label className="portrait-label">Character description</label>
            <textarea
              rows={3}
              aria-label={`description ${character.slug}`}
              value={descDraft}
              disabled={!editable}
              onChange={(e) => setDescDraft(e.target.value)}
            />
            {editable && (
              <div className="row">
                <button
                  disabled={busy !== null || !descDirty}
                  onClick={() =>
                    run("desc", () =>
                      editCast(id, character.slug, { visual_description: descDraft }),
                    )
                  }
                >
                  {busy === "desc" ? "Saving…" : "Save description"}
                </button>
              </div>
            )}
          </>
        )}

        {editable && (
          <div className="row" style={{ marginTop: 6 }}>
            <button
              className="primary"
              disabled={busy !== null}
              title="Draw this portrait again with a fresh result"
              onClick={() =>
                run("regen", async () => {
                  await regenPlate(id, prompt.page_id);
                  setBump((b) => b + 1);
                })
              }
            >
              {busy === "regen" ? "Regenerating…" : "Regenerate"}
            </button>
          </div>
        )}
        <ErrorNotice error={error} />
      </div>
    </div>
  );
}
