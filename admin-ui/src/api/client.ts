// A tiny typed fetch wrapper for the admin API. All paths are relative to /api/admin (dev: proxied
// to :8720 by Vite; prod: same-origin under /admin). Non-2xx responses throw ApiError carrying the
// status and the parsed `detail`, so screens can special-case the review-gate 422 (missing prompts)
// and the 409/502 degradations without re-parsing bodies.

import type {
  ApproveError,
  Cast,
  CreateBookBody,
  CreateBookResponse,
  DensityPreset,
  GutendexResult,
  Job,
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

export const createBook = (body: CreateBookBody) =>
  request<CreateBookResponse>("POST", "/books", body);

export const editChapters = (
  id: string,
  chapters: { title: string | null; paragraphs: string[] }[],
) => request<Job>("PUT", `/books/${id}/chapters`, { chapters });

export const startJob = (id: string) => request<Job>("POST", `/jobs/${id}/start`);
export const pauseJob = (id: string) => request<Job>("POST", `/jobs/${id}/pause`);
export const resumeJob = (id: string) => request<Job>("POST", `/jobs/${id}/resume`);

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

export const reselect = (id: string, densityPreset: DensityPreset) =>
  request<Selection>("POST", `/books/${id}/reselect`, { density_preset: densityPreset });

// The post-render thumb URL (served by GET /books/{id}/plate-image/{page_id}.png).
export const plateImageUrl = (id: string, pageId: string) =>
  `${BASE}/books/${id}/plate-image/${pageId}.png`;

// Re-export ApproveError type guard helper for the approve flow.
export type { ApproveError };
export function isApproveError(detail: unknown): detail is ApproveError {
  return (
    !!detail &&
    typeof detail === "object" &&
    "page_ids" in detail &&
    Array.isArray((detail as ApproveError).page_ids)
  );
}
