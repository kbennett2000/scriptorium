import type { Storage } from "../shell";
import { artsetCheckout, HttpArtsetClient } from "./artsetCheckout";
import { ApiError } from "./client";

// Post-publish per-plate picture edit (ADR-0033) — the reader's network boundary for the Edit screen.
// Lives in shelf/ because the ESLint fence bans fetch/HTTP everywhere else. The overlay is served as
// the reserved "edits" set, so committing then downloads it via the existing artsetCheckout, and the
// replaced image + caption are Resident (shown offline) thereafter.

const BASE = import.meta.env.VITE_SERVER_URL ?? "";
const EDITS_SET = "edits";

/** A pickable illustration style (styles catalog, from the server). */
export interface StyleOption {
  id: string;
  name: string;
}

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
  /** Style/model of the reader (base book or active set) this edit derives from — picker defaults. */
  style_id: string;
  custom_style: string | null;
  model: string | null;
  quality_default: string;
  /** Override lists for the pickers. */
  styles: StyleOption[];
  models: string[];
  default_model: string | null;
  /** True iff this plate has a cast portrait to pin the character's likeness against. */
  has_cast_reference: boolean;
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
  /** The reader the edit is made from ("default" ⇒ base book, or a "set-…" id). */
  set_id?: string;
  /** Full harness override controls (each omitted ⇒ inherit the active reader's). */
  style_id?: string;
  custom_style?: string | null;
  model?: string | null;
  quality?: string;
  /** Character likeness: keep the cast portrait (default) and/or an uploaded base64 PNG override. */
  use_cast_reference?: boolean;
  reference?: string | null;
  reference_strength?: number | null;
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
  setId?: string,
): Promise<EditContext> {
  const q = setId ? `?set_id=${seg(setId)}` : "";
  const resp = await fetch(`${BASE}${plateBase(user, book, plateId)}/context${q}`);
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
