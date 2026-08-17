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
  /** True iff the imagegen service reports an animate model ready (gates the "Bring to life" UI). */
  video_available: boolean;
  /** Animate model wire ids the service reports ready ("wan-5b" / "remix-14b"). */
  animate_models: string[];
  /** A clip already accepted for this plate+scope (pre-fills the motion prompt), or null. */
  video: VideoInfo | null;
}

/** The provenance of an accepted clip (mirrors the artset-edits `video` descriptor, ADR-0037). */
export interface VideoInfo {
  motion_prompt: string;
  model?: string | null;
  frames?: number | null;
  fps?: number | null;
  seed?: number | null;
  created?: string;
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

// --- video (ADR-0037): animate a plate's current picture into a short clip ---

/** A generated-but-uncommitted video candidate. */
export interface VideoCandidate {
  token: string;
}

export interface VideoBody {
  motion_prompt: string;
  /** The reader the clip is made from ("default" ⇒ base book, or a "set-…" id). */
  set_id?: string;
  /** Animate model wire id ("wan-5b"/"remix-14b"); omitted ⇒ the service default. */
  model?: string | null;
  negative?: string | null;
  seed?: number | null;
  frames?: number | null;
  fps?: number | null;
}

/**
 * Animate the plate's current picture into a candidate clip. NOTE: this render takes MINUTES (and
 * the first one after an image job pauses to swap GPU models) — the request stays open the whole
 * time. Callers must show a long-running spinner.
 */
export async function generateVideoCandidate(
  user: string,
  book: string,
  plateId: string,
  body: VideoBody,
): Promise<VideoCandidate> {
  const resp = await fetch(`${BASE}${plateBase(user, book, plateId)}/video-candidate`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new ApiError(resp.status, `POST video-candidate → ${resp.status}`);
  return (await resp.json()) as VideoCandidate;
}

/** The URL of an uncommitted candidate clip — used directly as a <video src> (online-only preview). */
export function videoCandidateUrl(
  user: string,
  book: string,
  plateId: string,
  token: string,
): string {
  return `${BASE}${plateBase(user, book, plateId)}/video-candidate/${seg(token)}.mp4`;
}

/**
 * Accept the chosen candidate clip into the private overlay, then download the overlay so the clip
 * plays offline afterward (Resident) and the reader shows a play icon on the plate.
 */
export async function commitVideo(
  storage: Storage,
  user: string,
  book: string,
  plateId: string,
  token: string,
): Promise<void> {
  const resp = await fetch(`${BASE}${plateBase(user, book, plateId)}/video-commit`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ token }),
  });
  if (!resp.ok) throw new ApiError(resp.status, `POST video-commit → ${resp.status}`);
  await artsetCheckout(new HttpArtsetClient(), storage, user, book, EDITS_SET);
}
