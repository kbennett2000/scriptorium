// A tiny typed fetch wrapper for the admin API. All paths are relative to /api/admin (dev: proxied
// to :8720 by Vite; prod: same-origin under /admin). Non-2xx responses throw ApiError carrying the
// status and the parsed `detail`, so screens can special-case the review-gate 422 (missing prompts)
// and the 409/502 degradations without re-parsing bodies.

import type {
  ApproveError,
  Cast,
  CastApproveError,
  CreateBookBody,
  CreateBookResponse,
  DensityPreset,
  GpuStatus,
  GutendexResult,
  Job,
  ModelList,
  Prompt,
  ReviewPayload,
  Selection,
  Styles,
} from "./types";

const BASE = "/api/admin";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;
  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : `HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, headers: {} };
  if (body !== undefined) {
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const resp = await fetch(`${BASE}${path}`, init);
  const text = await resp.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }
  if (!resp.ok) {
    // FastAPI wraps errors as {detail: ...}; surface the detail directly.
    const detail =
      payload && typeof payload === "object" && "detail" in payload
        ? (payload as { detail: unknown }).detail
        : payload;
    throw new ApiError(resp.status, detail);
  }
  return payload as T;
}

// --- books & jobs (bake/api.py) ---------------------------------------------

export const listBooks = () =>
  request<{ books: Job[] }>("GET", "/books").then((r) => r.books);

export const getBook = (id: string) => request<Job>("GET", `/books/${id}`);

// Best-effort GPU/CPU status for the live indicator (never 500s server-side).
export const getGpuStatus = () => request<GpuStatus>("GET", "/gpu");

// Installed base models for the bake picker (ADR-0030). Best-effort: an unreachable imagegen
// service yields {models: [], default: null, reachable: false} so the wizard falls back to default.
export const getModels = () => request<ModelList>("GET", "/models");

export const createBook = (body: CreateBookBody) =>
  request<CreateBookResponse>("POST", "/books", body);

export const editChapters = (
  id: string,
  chapters: { title: string | null; paragraphs: string[] }[],
) => request<Job>("PUT", `/books/${id}/chapters`, { chapters });

export const startJob = (id: string) => request<Job>("POST", `/jobs/${id}/start`);
export const pauseJob = (id: string) => request<Job>("POST", `/jobs/${id}/pause`);
export const resumeJob = (id: string) => request<Job>("POST", `/jobs/${id}/resume`);

/** Permanently delete a book and everything it owns (bundle, jobs, every profile's sets + notes). */
export const deleteBook = (id: string) =>
  request<{ deleted: string; removed: string[] }>("DELETE", `/books/${id}`);

// --- review gate (bake/review_api.py) ---------------------------------------

export const searchGutendex = (q: string) =>
  request<{ results: GutendexResult[] }>(
    "GET",
    `/gutendex?q=${encodeURIComponent(q)}`,
  ).then((r) => r.results);

export const getStyles = () => request<Styles>("GET", "/styles");

export const getReview = (id: string) => request<ReviewPayload>("GET", `/books/${id}/review`);

export const editPrompt = (id: string, pageId: string, editedPrompt: string | null) =>
  request<Prompt>("PUT", `/books/${id}/review/prompt/${pageId}`, {
    edited_prompt: editedPrompt,
  });

export const editSelection = (id: string, change: { add?: string[]; remove?: string[] }) =>
  request<Selection>("PUT", `/books/${id}/review/selection`, {
    add: change.add ?? [],
    remove: change.remove ?? [],
  });

export const editCast = (
  id: string,
  slug: string,
  fields: { visual_description?: string; one_line?: string },
) => request<Cast["characters"][number]>("PUT", `/books/${id}/review/cast/${slug}`, fields);

export const approve = (id: string) => request<Job>("POST", `/books/${id}/approve`);

// Approve the cast-review gate (ADR-0032): advance cast_done -> cast_approved so the scene prompts
// derive from the approved descriptions. A 422 names any major still missing a description.
export const approveCast = (id: string) =>
  request<Job>("POST", `/books/${id}/approve-cast`);

// Approve the optional portrait gate (ADR-0025): advance portraits_review -> rendering so the page
// plates draw, seeded by the now-approved portraits.
export const approvePortraits = (id: string) =>
  request<Job>("POST", `/books/${id}/approve-portraits`);

export const reselect = (id: string, densityPreset: DensityPreset) =>
  request<Selection>("POST", `/books/${id}/reselect`, { density_preset: densityPreset });

// Re-render one plate with a fresh seed (POST …/plates/{id}/regen). Pre-publish overwrites the
// work-dir plate in place; post-publish writes an additive -rN variant and bumps the revision. The
// updated prompt doc (with bumped render.attempts) is returned.
export const regenPlate = (id: string, pageId: string) =>
  request<Prompt>("POST", `/books/${id}/plates/${pageId}/regen`);

// Upload an owner-supplied portrait image at the gate (ADR-0029): the server center-crops it to the
// 1024×1024 portrait square and stamps render.source='upload'. Multipart, so we bypass the JSON
// `request` helper and let the browser set the multipart boundary (never set Content-Type here).
export async function uploadPortrait(id: string, slug: string, file: File): Promise<Prompt> {
  const form = new FormData();
  form.append("file", file);
  const resp = await fetch(`${BASE}/books/${id}/portraits/${slug}/upload`, {
    method: "POST",
    body: form,
  });
  const text = await resp.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }
  if (!resp.ok) {
    const detail =
      payload && typeof payload === "object" && "detail" in payload
        ? (payload as { detail: unknown }).detail
        : payload;
    throw new ApiError(resp.status, detail);
  }
  return payload as Prompt;
}

// The post-render thumb URL (served by GET /books/{id}/plate-image/{page_id}.png).
export const plateImageUrl = (id: string, pageId: string) =>
  `${BASE}/books/${id}/plate-image/${pageId}.png`;

// Re-export ApproveError type guard helper for the approve flow.
export type { ApproveError, CastApproveError };
export function isApproveError(detail: unknown): detail is ApproveError {
  return (
    !!detail &&
    typeof detail === "object" &&
    "page_ids" in detail &&
    Array.isArray((detail as ApproveError).page_ids)
  );
}

export function isCastApproveError(detail: unknown): detail is CastApproveError {
  return (
    !!detail &&
    typeof detail === "object" &&
    "slugs" in detail &&
    Array.isArray((detail as CastApproveError).slugs)
  );
}
