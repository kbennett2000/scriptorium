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
  | "rendering"
  | "rendered"
  | "published"
  | "waiting_gpu"
  | "paused"
  | "failed";

// A recorded per-unit failure (bake/runner.py). Opaque runtime shape — treated as untyped.
export type FailedUnit = Record<string, unknown>;

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
