import { useState } from "react";

import { getReview, plateImageUrl, regenPlate } from "../../api/client";
import { ErrorNotice, errorText, Loading, Notice, useAsync } from "../../components/common";
import { POSTRENDER_ENABLED } from "../../config";
import type { ReviewPayload } from "../../api/types";
import { navigate } from "../../routes";

// Post-render review (§11.3): the same plate set, now with rendered thumbs + a per-plate Regen
// (POST …/plates/{id}/regen). Feature-flagged (POSTRENDER_ENABLED). The "placeholder" banner shows
// only while the render is still the S9 demo stub (review.render_stub) — real render (S10) clears it.
export function PostRender({ id }: { id: string }) {
  const { data, error, loading, reload } = useAsync(() => getReview(id), [id]);

  if (!POSTRENDER_ENABLED) {
    return (
      <section>
        <Crumbs id={id} />
        <Notice kind="warn">The post-render view is disabled in this build.</Notice>
      </section>
    );
  }

  return (
    <section>
      <Crumbs id={id} />
      {loading && <Loading what="plates" />}
      <ErrorNotice error={error} prefix="Could not load plates" />
      {data && <PostRenderBody id={id} review={data} reload={reload} />}
    </section>
  );
}

function Crumbs({ id }: { id: string }) {
  return (
    <div className="crumbs">
      <a onClick={() => navigate({ name: "list" })}>Books</a> ›{" "}
      <a onClick={() => navigate({ name: "detail", id })}>{id}</a> › Post-render
    </div>
  );
}

function PostRenderBody({
  id,
  review,
  reload,
}: {
  id: string;
  review: ReviewPayload;
  reload: () => void;
}) {
  // Page plates that have pixels, plus the cover/portrait pseudo-plates (all render).
  const pagePlates = review.selection.plates.filter(
    (p) => p.status === "rendered" || p.status === "approved",
  );
  const pseudo = review.prompts.filter((p) => !/^\d{4}$/.test(p.page_id));
  const rows: { pageId: string; label: string }[] = [
    ...pagePlates.map((p) => ({ pageId: p.page_id, label: p.reason })),
    ...pseudo.map((p) => ({ pageId: p.page_id, label: "pseudo-plate" })),
  ];

  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  // Bump per-plate to cache-bust the thumb after a re-render (same URL, new bytes).
  const [bump, setBump] = useState<Record<string, number>>({});

  async function regen(pageId: string) {
    setBusy(pageId);
    setActionError(null);
    try {
      await regenPlate(id, pageId);
      setBump((b) => ({ ...b, [pageId]: (b[pageId] ?? 0) + 1 }));
      reload();
    } catch (err) {
      setActionError(err);
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <div className="spread">
        <h2>Post-render — {review.book_id}</h2>
        <span className="badge state">{review.state}</span>
      </div>
      {review.render_stub && (
        <Notice kind="warn">
          These are <strong>placeholder</strong> renders from the demo stub (FakeImagegen), not
          final art.
        </Notice>
      )}
      {actionError != null && (
        <Notice kind="error">Regen failed: {errorText(actionError)}</Notice>
      )}

      <table>
        <thead>
          <tr>
            <th style={{ width: 110 }}>Thumb</th>
            <th style={{ width: 70 }}>Plate</th>
            <th>Prompt</th>
            <th style={{ width: 90 }}>Regen</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const prompt = review.prompts.find((p) => p.page_id === r.pageId);
            const v = bump[r.pageId] ?? 0;
            return (
              <tr key={r.pageId}>
                <td>
                  <img
                    className="plate-thumb"
                    src={`${plateImageUrl(id, r.pageId)}?v=${v}`}
                    alt={`plate ${r.pageId}`}
                    loading="lazy"
                  />
                </td>
                <td className="mono">
                  {r.pageId}
                  <div className="muted" style={{ fontSize: 11 }}>{r.label}</div>
                </td>
                <td className="mono" style={{ fontSize: 12 }}>
                  {prompt?.final_subject_prompt ?? <span className="muted">—</span>}
                </td>
                <td>
                  <button
                    disabled={busy !== null}
                    onClick={() => regen(r.pageId)}
                    title="Re-render this plate with a fresh seed"
                  >
                    {busy === r.pageId ? "Regen…" : "Regen"}
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </>
  );
}
