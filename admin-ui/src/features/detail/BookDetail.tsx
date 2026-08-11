import { useEffect, useState } from "react";

import {
  deleteBook,
  editChapters,
  getBook,
  getGpuStatus,
  pauseJob,
  resumeJob,
  startJob,
} from "../../api/client";
import { ErrorNotice, errorText, Loading, Notice, useAsync } from "../../components/common";
import type { GpuStatus, Job, JobStateName } from "../../api/types";
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
  "approved", "portraits_rendering", "portraits_review", "rendering", "rendered", "published",
];

const REVIEW_STATES: JobStateName[] = ["prompts_draft", "in_review", "approved"];
// Optional portrait gate (ADR-0025): the "Review portraits" screen is reachable while portraits
// draw and while the job rests at the gate.
const PORTRAIT_STATES: JobStateName[] = ["portraits_rendering", "portraits_review"];
const POSTRENDER_STATES: JobStateName[] = ["rendering", "rendered", "published"];

// States where the bake is not moving on its own: done, dead, or held. Everything else is "active"
// and the page auto-refreshes so you can watch it progress without clicking Refresh.
const AT_REST: JobStateName[] = ["published", "failed", "paused"];
function isActive(state: JobStateName): boolean {
  return !AT_REST.includes(state);
}

// Seconds without any progress before we flag a possible stall. Generous so a single slow unit (one
// image can take ~a minute) never trips it — only a real wedge (the 67-minute case) does.
const STALL_SECS = 180;

// Plain-language "what's happening now" for each milestone we could be working toward.
const MILESTONE_ACTIVITY: Record<string, string> = {
  ingested: "Reading the book",
  cast_done: "Finding the characters",
  ledger_done: "Reading the scenes",
  selected: "Choosing which moments to illustrate",
  prompts_draft: "Writing the picture instructions",
  approved: "Getting it approved",
  rendered: "Drawing the pictures",
  published: "Packaging the finished book",
};

function reached(current: JobStateName, milestone: JobStateName): boolean {
  const ci = CHAIN_ORDER.indexOf(current);
  const mi = CHAIN_ORDER.indexOf(milestone);
  return ci >= 0 && mi >= 0 && ci >= mi;
}

// The first milestone not yet reached = the one the bake is currently working toward (so a
// `*_running` state lights up the milestone it will produce). -1 once everything is reached.
function activeMilestoneIndex(state: JobStateName): number {
  return MILESTONES.findIndex((m) => !reached(state, m.state));
}

function fmtElapsed(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}

// The live CPU/GPU indicator. Green when the text brain is on the graphics card, amber when it has
// spilled onto the CPU (slow) — the very failure mode this page is meant to make visible.
function GpuBadge({ status }: { status: GpuStatus | null }) {
  if (!status) return null;
  const look = {
    gpu: { label: "⚡ GPU", bg: "#e9f6ee", fg: "#1c7a3a", bd: "#a6d6b8" },
    cpu: { label: "⚠ CPU (slow)", bg: "#fdeede", fg: "#9a5b00", bd: "#f0cfa0" },
    idle: { label: "GPU idle", bg: "#eef", fg: "#667", bd: "#dde" },
    unknown: { label: "GPU —", bg: "#eee", fg: "#999", bd: "#ddd" },
  }[status.summary];
  const util = status.gpu.util_percent;
  const showUtil = util != null && status.summary !== "unknown";
  const title = status.text_model.name
    ? `${status.text_model.name} on ${status.text_model.processor ?? "?"}`
    : "no text model loaded";
  return (
    <span
      className="badge"
      title={title}
      style={{ background: look.bg, color: look.fg, borderColor: look.bd }}
    >
      {look.label}
      {showUtil ? ` · ${util}%` : ""}
    </span>
  );
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
  const [gpu, setGpu] = useState<GpuStatus | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [stepSince, setStepSince] = useState(() => Date.now());

  const active = isActive(job.state);

  // Auto-refresh while the bake is in motion: pull the job every few seconds (and tick the clock
  // for the elapsed readout) so progress is visible without clicking Refresh. Stops at rest.
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => {
      reload();
      setNow(Date.now());
    }, 3500);
    return () => clearInterval(id);
  }, [active, reload]);

  // Reset the "time on this step" clock whenever the phase changes.
  useEffect(() => {
    setStepSince(Date.now());
    setNow(Date.now());
  }, [job.state]);

  // Poll the CPU/GPU indicator independently (cheap, best-effort — errors just clear the badge).
  useEffect(() => {
    let alive = true;
    const tick = () =>
      getGpuStatus()
        .then((s) => alive && setGpu(s))
        .catch(() => alive && setGpu(null));
    tick();
    const id = setInterval(tick, 3500);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

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
  const canPortraits = PORTRAIT_STATES.includes(job.state);
  const canPostRender = POSTRENDER_STATES.includes(job.state);

  // Per-step progress + liveness (server-provided; see bake/progress.py).
  const prog = job.progress;
  const hasBar = !!prog && prog.units_total != null && prog.units_done != null;
  const pct = hasBar ? Math.round((prog!.units_done! / Math.max(1, prog!.units_total!)) * 100) : 0;
  const sinceActivity = job.seconds_since_activity ?? 0;
  const stalled = !!job.expecting_progress && sinceActivity > STALL_SECS;

  return (
    <>
      <div className="spread">
        <h2>{job.title || "(untitled)"}</h2>
        <div className="row" style={{ gap: 6 }}>
          <GpuBadge status={gpu} />
          <span className="badge state">{job.state}</span>
        </div>
      </div>
      <div className="muted mono" style={{ marginBottom: 12 }}>{job.book_id}</div>

      {job.state === "failed" && <Notice kind="error">This bake failed. See failed units below.</Notice>}
      {job.state === "waiting_gpu" && (
        <Notice kind="warn">Waiting for a GPU service (parked from {job.prev_state}).</Notice>
      )}
      {job.state === "paused" && <Notice kind="warn">Paused (was {job.prev_state}).</Notice>}
      {stalled && (
        <Notice kind="warn">
          No progress for {fmtElapsed(sinceActivity * 1000)} — it may be waiting on a GPU service or
          stuck. Try Refresh; if it stays stuck, Pause then Resume.
        </Notice>
      )}

      {/* Phase progress */}
      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Progress</h3>
        {(() => {
          const activeIdx = activeMilestoneIndex(job.state);
          const activity = activeIdx >= 0 ? MILESTONE_ACTIVITY[MILESTONES[activeIdx].state] : null;
          // Only claim "working" when the SERVER says the runner should be advancing; otherwise say
          // plainly what it's waiting for — a ticking clock must never imply work that isn't happening.
          const working = !!job.expecting_progress;
          const awaitingApproval = job.state === "prompts_draft" || job.state === "in_review";
          const waitingLabel =
            job.state === "published" || job.state === "waiting_gpu" || job.state === "failed"
              ? null
              : !job.started
                ? "Waiting to start"
                : awaitingApproval
                  ? "Waiting for your approval"
                  : active && !working
                    ? "Waiting…"
                    : null;
          return (
            <>
              {working && activity && (
                <>
                  <p style={{ marginTop: 0, marginBottom: hasBar ? 6 : 10, color: "#2a5db0", fontWeight: 600 }}>
                    ⏳ Working on: {activity}…{" "}
                    {hasBar && <span>{prog!.units_done} / {prog!.units_total}{" "}</span>}
                    <span className="muted" style={{ fontWeight: 400 }}>
                      ({fmtElapsed(now - stepSince)} on this step · updated {Math.round(sinceActivity)}s ago
                      · refreshing automatically)
                    </span>
                  </p>
                  {hasBar && (
                    <div className="progress-bar" style={{ marginBottom: 10 }}>
                      <div className="progress-fill" style={{ width: `${pct}%` }} />
                    </div>
                  )}
                </>
              )}
              {!working && waitingLabel && (
                <p className="muted" style={{ marginTop: 0, marginBottom: 10, fontWeight: 600 }}>
                  ⏸ {waitingLabel}
                  {awaitingApproval && " — use Open Review below."}
                </p>
              )}
              {job.state === "published" && (
                <p style={{ marginTop: 0, marginBottom: 10, color: "#1c7a3a", fontWeight: 600 }}>
                  ✓ Done — the book is published.
                </p>
              )}
              {job.unattended && active && (
                <p className="muted" style={{ marginTop: 0, marginBottom: 10, fontSize: 12 }}>
                  Unattended — this book starts itself and finishes on its own; no clicks needed.
                </p>
              )}
              <div className="row">
                {MILESTONES.map((m, i) => {
                  const done = reached(job.state, m.state);
                  const inProgress = active && !done && i === activeIdx;
                  return (
                    <span
                      key={m.state}
                      className="badge"
                      style={{
                        background: inProgress ? "#e5edf7" : done ? "#e9f6ee" : "#eee",
                        color: inProgress ? "#2a5db0" : done ? "#1c7a3a" : "#999",
                        borderColor: inProgress ? "#bcd0ea" : done ? "#a6d6b8" : "#ddd",
                      }}
                    >
                      {done ? "✓ " : inProgress ? "▸ " : "· "}
                      {m.label}
                    </span>
                  );
                })}
              </div>
            </>
          );
        })()}
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
          {canPortraits && (
            <button
              className={job.state === "portraits_review" ? "primary" : undefined}
              onClick={() => navigate({ name: "portraits", id: job.book_id })}
            >
              {job.state === "portraits_review" ? "Review portraits" : "Portraits…"}
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

      <DangerZone job={job} />
    </>
  );
}

// Permanent deletion. Irreversible and wide-reaching (the bundle, every profile's private picture
// sets, and everyone's highlights/notes for this book all go), so it's gated behind a typed
// confirmation — the operator must type the exact book title before the button enables.
function DangerZone({ job }: { job: Job }) {
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const title = job.title || "(untitled)";

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await deleteBook(job.book_id);
      navigate({ name: "list" });
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <div className="panel danger">
      <h3 style={{ marginTop: 0 }}>Delete this book permanently</h3>
      <p className="muted" style={{ marginTop: 0 }}>
        This removes the book for good — its pictures, <strong>everyone’s</strong> private picture
        sets for it, and <strong>everyone’s</strong> highlights and notes. This cannot be undone. To
        confirm, type the book’s title: <code>{title}</code>
      </p>
      <div className="row">
        <input
          aria-label="type the title to confirm deletion"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          placeholder={title}
        />
        <button
          className="destructive"
          disabled={busy || confirm !== title}
          onClick={() => void remove()}
        >
          {busy ? "Deleting…" : "Delete permanently"}
        </button>
      </div>
      <ErrorNotice error={error} prefix="Delete failed" />
    </div>
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
