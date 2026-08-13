import type { Storage } from "../shell";
import { artsetCheckout, HttpArtsetClient } from "./artsetCheckout";
import { ApiError } from "./client";

// Post-publish per-plate picture edit (ADR-0033) — the reader's network boundary for the Edit screen.
// Lives in shelf/ because the ESLint fence bans fetch/HTTP everywhere else. The overlay is served as
// the reserved "edits" set, so committing then downloads it via the existing artsetCheckout, and the
// replaced image + caption are Resident (shown offline) thereafter.

const BASE = import.meta.env.VITE_SERVER_URL ?? "";
const EDITS_SET = "edits";

/** The editor pre-fill for one plate (mirrors the server's edits.plate_context). */
export interface EditContext {
  plate_id: string;
  prompt: string;
  negative: string;
  seed: number | null;
  width: number;
  height: number;
  denoise_default: number;
  caption: string;
}

/** A generated-but-uncommitted candidate. */
export interface Candidate {
  token: string;
  width: number;
  height: number;
}

export interface GenerateBody {
  prompt: string;
  negative?: string;
  seed?: number | null;
  denoise?: number;
}

function seg(s: string): string {
  return encodeURIComponent(s);
}

function plateBase(user: string, book: string, plateId: string): string {
  return `/api/artsets/${seg(user)}/${seg(book)}/${EDITS_SET}/${seg(plateId)}`;
}

export async function fetchEditContext(
  user: string,
  book: string,
  plateId: string,
): Promise<EditContext> {
  const resp = await fetch(`${BASE}${plateBase(user, book, plateId)}/context`);
  if (!resp.ok) throw new ApiError(resp.status, `GET edit context → ${resp.status}`);
  return (await resp.json()) as EditContext;
}

export async function generateCandidate(
  user: string,
  book: string,
  plateId: string,
  body: GenerateBody,
): Promise<Candidate> {
  const resp = await fetch(`${BASE}${plateBase(user, book, plateId)}/candidate`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new ApiError(resp.status, `POST candidate → ${resp.status}`);
  return (await resp.json()) as Candidate;
}

/** The URL of an uncommitted candidate PNG — used directly as an <img src> (online-only preview). */
export function candidateUrl(user: string, book: string, plateId: string, token: string): string {
  return `${BASE}${plateBase(user, book, plateId)}/candidate/${seg(token)}.png`;
}

/**
 * Commit the chosen candidate + caption into the private overlay, then download the overlay so the
 * replacement shows offline afterward (Resident, exactly like a picture set).
 */
export async function commitEdit(
  storage: Storage,
  user: string,
  book: string,
  plateId: string,
  token: string,
  caption: string,
): Promise<void> {
  const resp = await fetch(`${BASE}${plateBase(user, book, plateId)}/commit`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ token, caption }),
  });
  if (!resp.ok) throw new ApiError(resp.status, `POST commit → ${resp.status}`);
  await artsetCheckout(new HttpArtsetClient(), storage, user, book, EDITS_SET);
}
