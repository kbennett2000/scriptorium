// Hand-written TypeScript for the admin API shapes that have NO JSON Schema (the durable Job
// record and the review-payload wrapper are gitignored runtime state, not bundle interchange —
// see NOTES "From S9a"). The nested *bundle* shapes (selection/cast/prompt/styles) DO come from
// the generated schema types via @scriptorium/shared, and are re-exported here so screens import
// everything from one place.

import type { Cast, Prompt, Selection, Styles } from "@scriptorium/shared";

export type { Cast, Prompt, Selection, Styles };

// The bake job state machine (server: bake/job.py JobState). Kept as a union so screens can gate
// controls by phase without magic strings.
export type JobStateName =
  | "created"
  | "ingested"
  | "mentions_running"
  | "mentions_done"
  | "cast_running"
  | "cast_done"
  | "ledger_running"
  | "ledger_done"
  | "selected"
  | "prompts_running"
  | "prompts_draft"
  | "in_review"
  | "approved"
  | "portraits_rendering"
  | "portraits_review"
  | "rendering"
  | "rendered"
  | "published"
  | "waiting_gpu"
  | "paused"
  | "failed"
  // Per-user picture-set render lifecycle (artsets), shown nested under a book in the Books list.
  | "set_rendering"
  | "set_done";

// A recorded per-unit failure (bake/runner.py). Opaque runtime shape — treated as untyped.
export type FailedUnit = Record<string, unknown>;

// GET /api/admin/gpu (server: gpu_probe.probe_gpu) — best-effort; fields degrade to null/"unknown".
export interface GpuStatus {
  gpu: {
    present: boolean;
    util_percent: number | null;
    mem_used_mib: number | null;
    mem_total_mib: number | null;
  };
  text_model: {
    loaded: boolean | null;
    name: string | null;
    processor: "gpu" | "cpu" | "mixed" | null;
  };
  summary: "gpu" | "cpu" | "idle" | "unknown";
}

// GET /api/admin/books/{id} and each item of GET /api/admin/books — Job.to_dict() (bake/api.py).
export interface Job {
  id: string;
  book_id: string;
  state: JobStateName;
  source: Record<string, unknown>;
  bake_config: Record<string, unknown>;
  title: string | null;
  warnings: string[];
  prompt_warnings: Record<string, string[]>;
  render_stub: boolean;
  failed_units: FailedUnit[];
  prev_state: JobStateName | null;
  started: boolean;
  created_at: string;
  updated_at: string;
  // Read-time progress + liveness added by GET /books/{id} (server bake/progress.py). Optional so
  // older/other callers of the Job shape stay valid.
  progress?: { units_done: number | null; units_total: number | null };
  server_now?: string;
  seconds_since_activity?: number;
  expecting_progress?: boolean;
  unattended?: boolean;
}

// GET /api/admin/books/{id}/review (bake/review_api.py get_review).
export interface ReviewPayload {
  book_id: string;
  state: JobStateName;
  selection: Selection;
  cast: Cast;
  prompts: Prompt[];
  warnings: string[];
  prompt_warnings: Record<string, string[]>;
  failed_units: FailedUnit[];
  beats: Record<string, string>;
  // True while the plates are S9-stub placeholders (real render clears it) — gates the banner.
  render_stub: boolean;
  // {slug: page plates this character's portrait will condition} — computed server-side with P7's
  // own resolver (ADR-0028). Drives the portrait gate's review order.
  portrait_anchor_counts: Record<string, number>;
  // {portrait-{slug}: whether that portrait's PNG exists on disk yet}. With the curated gate
  // (ADR-0029) portraits start blank and are generated/uploaded on demand, so the screen shows a
  // "Generate" affordance for the false entries instead of a broken image.
  portrait_rendered: Record<string, boolean>;
}

// GET /api/admin/models (bake/api.py list_models) — installed base models for the picker (ADR-0030).
export interface ModelList {
  models: string[];
  default: string | null;
  reachable: boolean;
}

// GET /api/admin/gutendex?q= (one trimmed result).
export interface GutendexResult {
  id: number | null;
  title: string | null;
  authors: string[];
  download_url: string | null;
}

// POST /api/admin/books request body (bake/api.py CreateBookBody).
export interface CreateBookBody {
  source: {
    kind: "gutenberg" | "text" | "markdown";
    gutenberg_id?: number | null;
    text?: string | null;
    filename?: string | null;
    title?: string | null;
    author?: string | null;
    language?: string | null;
  };
  bake: {
    style_id: string;
    density_preset: "lavish" | "classic" | "sparse";
    images_per_scene: number;
    era?: string | null;
    portraits_enabled: boolean;
    // Optional portrait-review gate (ADR-0025): pause after portraits render so the owner can
    // eyeball / edit / regenerate each one before the rest of the book draws.
    portrait_review: boolean;
    // Optional base model / checkpoint (ADR-0030); null → the imagegen service's default.
    model?: string | null;
    title?: string | null;
    author?: string | null;
  };
}

// POST /api/admin/books trimmed response (NOT the full job — fetch the book separately for that).
export interface CreateBookResponse {
  book_id: string;
  state: JobStateName;
  warnings: string[];
}

// The 422 body from POST /api/admin/books/{id}/approve when a renderable plate lacks a prompt.
export interface ApproveError {
  error: string;
  page_ids: string[];
}

export type DensityPreset = "lavish" | "classic" | "sparse";
