import { useState } from "react";

import {
  editChapters,
  getBook,
  pauseJob,
  resumeJob,
  startJob,
} from "../../api/client";
import { ErrorNotice, errorText, Loading, Notice, useAsync } from "../../components/common";
import type { Job, JobStateName } from "../../api/types";
import { navigate } from "../../routes";

// The ordered bake milestones (bake/job.py chain). Off-chain states (waiting_gpu/paused/failed) are
// shown as the live status, not as a milestone.
const MILESTONES: { state: JobStateName; label: string }[] = [
  { state: "ingested", label: "Ingested (P0)" },
  { state: "cast_done", label: "Cast (P1–P2)" },
  { state: "ledger_done", label: "Ledger (P3)" },
  { state: "selected", label: "Selected (P4)" },
  { state: "prompts_draft", label: "Prompts (P5)" },
  { state: "approved", label: "Approved (review gate)" },
  { state: "rendered", label: "Rendered (P7)" },
  { state: "published", label: "Published (P8)" },
];
const CHAIN_ORDER: JobStateName[] = [
  "created", "ingested", "mentions_running", "mentions_done", "cast_running", "cast_done",
  "ledger_running", "ledger_done", "selected", "prompts_running", "prompts_draft", "in_review",
  "approved", "rendering", "rendered", "published",
];

const REVIEW_STATES: JobStateName[] = ["prompts_draft", "in_review", "approved"];
const POSTRENDER_STATES: JobStateName[] = ["rendering", "rendered", "published"];

function reached(current: JobStateName, milestone: JobStateName): boolean {
  const ci = CHAIN_ORDER.indexOf(current);
  const mi = CHAIN_ORDER.indexOf(milestone);
  return ci >= 0 && mi >= 0 && ci >= mi;
}

export function BookDetail({ id }: { id: string }) {
  const { data: job, error, loading, reload } = useAsync(() => getBook(id), [id]);

  return (
    <section>
      <div className="crumbs">
        <a onClick={() => navigate({ name: "list" })}>Books</a> › {id}
      </div>
      {loading && <Loading what="book" />}
      <ErrorNotice error={error} prefix="Could not load book" />
      {job && <BookDetailBody job={job} reload={reload} />}
    </section>
  );
}

function BookDetailBody({ job, reload }: { job: Job; reload: () => void }) {
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<unknown>(null);

  async function control(fn: () => Promise<Job>) {
    setBusy(true);
    setActionError(null);
    try {
      await fn();
      reload();
    } catch (err) {
      setActionError(err);
    } finally {
      setBusy(false);
    }
  }

  const promptWarningPages = Object.keys(job.prompt_warnings);
  const canReview = REVIEW_STATES.includes(job.state);
  const canPostRender = POSTRENDER_STATES.includes(job.state);

  return (
    <>
      <div className="spread">
        <h2>{job.title || "(untitled)"}</h2>
        <span className="badge state">{job.state}</span>
      </div>
      <div className="muted mono" style={{ marginBottom: 12 }}>{job.book_id}</div>

      {job.state === "failed" && <Notice kind="error">This bake failed. See failed units below.</Notice>}
      {job.state === "waiting_gpu" && (
        <Notice kind="warn">Waiting for a GPU service (parked from {job.prev_state}).</Notice>
      )}
      {job.state === "paused" && <Notice kind="warn">Paused (was {job.prev_state}).</Notice>}

      {/* Phase progress */}
      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Progress</h3>
        <div className="row">
          {MILESTONES.map((m) => {
            const done = reached(job.state, m.state);
            const current = job.state === m.state;
            return (
              <span
                key={m.state}
                className="badge"
                style={{
                  background: current ? "#e5edf7" : done ? "#e9f6ee" : "#eee",
                  color: current ? "#2a5db0" : done ? "#1c7a3a" : "#999",
                  borderColor: current ? "#bcd0ea" : done ? "#a6d6b8" : "#ddd",
                }}
              >
                {done ? "✓ " : current ? "▸ " : "· "}
                {m.label}
              </span>
            );
          })}
        </div>
      </div>

      {/* Job controls */}
      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Controls</h3>
        <div className="row">
          <button
            disabled={busy || job.started}
            onClick={() => control(() => startJob(job.book_id))}
          >
            {job.started ? "Started" : "Start"}
          </button>
          <button
            disabled={busy || ["paused", "failed", "published"].includes(job.state)}
            onClick={() => control(() => pauseJob(job.book_id))}
          >
            Pause
          </button>
          <button
            disabled={busy || job.state !== "paused"}
            onClick={() => control(() => resumeJob(job.book_id))}
          >
            Resume
          </button>
          <button onClick={reload} disabled={busy}>
            Refresh
          </button>
          {canReview && (
            <button className="primary" onClick={() => navigate({ name: "review", id: job.book_id })}>
              Open Review
            </button>
          )}
          {canPostRender && (
            <button onClick={() => navigate({ name: "postrender", id: job.book_id })}>
              Post-render
            </button>
          )}
        </div>
        <ErrorNotice error={actionError} prefix="Action failed" />
      </div>

      {/* Warnings */}
      {job.warnings.length > 0 && (
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>Ingestion warnings</h3>
          <ul style={{ margin: 0 }}>
            {job.warnings.map((w, i) => (
              <li key={i} className="muted">{w}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Prompt warnings */}
      {promptWarningPages.length > 0 && (
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>Prompt warnings (P5)</h3>
          <ul style={{ margin: 0 }}>
            {promptWarningPages.map((pid) => (
              <li key={pid} className="muted">
                <span className="mono">{pid}</span>: {job.prompt_warnings[pid].join("; ")}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Failed units */}
      {job.failed_units.length > 0 && (
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>Failed units</h3>
          <pre className="mono" style={{ overflowX: "auto", fontSize: 12 }}>
            {JSON.stringify(job.failed_units, null, 2)}
          </pre>
        </div>
      )}

      {/* Chapter editor — pre-P1 only */}
      {job.state === "ingested" && <ChapterEditor bookId={job.book_id} onSaved={reload} />}
    </>
  );
}

// Minimal pre-P1 chapter-break editor. There is no admin endpoint to READ the current chapter
// paragraphs (only PUT to replace them), so the editor takes a raw chapters JSON array and re-runs
// P0 pagination. A richer editor waits on a GET-chapters endpoint (see NOTES From S9b).
function ChapterEditor({ bookId, onSaved }: { bookId: string; onSaved: () => void }) {
  const [raw, setRaw] = useState(
    '[\n  { "title": "Chapter I", "paragraphs": ["First paragraph.", "Second paragraph."] }\n]',
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [ok, setOk] = useState(false);

  async function save() {
    setBusy(true);
    setError(null);
    setOk(false);
    let chapters: { title: string | null; paragraphs: string[] }[];
    try {
      chapters = JSON.parse(raw);
    } catch (err) {
      setError(new Error(`Invalid JSON: ${errorText(err)}`));
      setBusy(false);
      return;
    }
    try {
      await editChapters(bookId, chapters);
      setOk(true);
      onSaved();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel">
      <h3 style={{ marginTop: 0 }}>Chapter breaks (editable pre-P1)</h3>
      <p className="muted" style={{ marginTop: 0 }}>
        Replaces the chapter structure and re-runs pagination. Provide a JSON array of{" "}
        <code>{"{ title, paragraphs[] }"}</code>. Only available while the book is <code>ingested</code>.
      </p>
      <textarea rows={8} aria-label="chapters json" value={raw} onChange={(e) => setRaw(e.target.value)} />
      <div className="row" style={{ marginTop: 6 }}>
        <button disabled={busy} onClick={save}>
          {busy ? "Saving…" : "Re-paginate"}
        </button>
        {ok && <span className="muted">Saved.</span>}
      </div>
      <ErrorNotice error={error} />
    </div>
  );
}
