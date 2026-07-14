// Local annotation persistence (DESIGN §4.5, §14). One doc per {user, book} in the sync wire shape,
// so R3's sync client can lift these files straight into the server's last-writer-wins merge. R2 only
// reads/writes locally — no server contact, no merge here.
//
// Every write is deliberately R3-mergeable: uuid `id` (the merge key), ISO-8601 `created`/`modified`,
// and deletion as a TOMBSTONE (`deleted: true`, `modified` bumped) rather than a splice — LWW needs the
// dead record to outrank a stale peer that still has it live.
//
// File path is `annotations/{user}/{bookId}.json` — OUTSIDE `books/{bookId}/`, so shelf Remove (which
// deletes only `books/{id}/`) keeps annotations, matching the shelf's "annotations are kept" copy and
// mirroring where `readerview/position.ts` puts positions. R2 has one dev-default user; R3's profile
// picker replaces `DEV_USER_ID` (and will also migrate positions under a `{user}/` segment).

import type { Annotations } from "@scriptorium/shared";

import type { Storage } from "../shell";
import type { Anchor } from "./anchors";
import type { HighlightColor } from "./segments";

/** A single annotation record (highlight | note | bookmark), including tombstones. */
export type Annotation = Annotations["annotations"][number];

/** The single household profile used until R3 ships the picker. A valid `users[].id` slug. */
export const DEV_USER_ID = "default";

function annotationsPath(user: string, bookId: string): string {
  return `annotations/${user}/${bookId}.json`;
}

/** Read a book's annotations for a user, or a fresh empty doc if none exist / the file is unreadable. */
export async function readAnnotations(
  storage: Storage,
  bookId: string,
  user: string = DEV_USER_ID,
): Promise<Annotations> {
  const path = annotationsPath(user, bookId);
  if (await storage.exists(path)) {
    try {
      return JSON.parse(await storage.readText(path)) as Annotations;
    } catch {
      // fall through to a fresh doc on a corrupt file
    }
  }
  return { book_id: bookId, user_id: user, annotations: [] };
}

async function writeDoc(
  storage: Storage,
  bookId: string,
  user: string,
  doc: Annotations,
): Promise<Annotations> {
  await storage.writeText(annotationsPath(user, bookId), JSON.stringify(doc));
  return doc;
}

function makeAnnotation(
  fields: Pick<Annotation, "type" | "page_id" | "anchor"> &
    Partial<Pick<Annotation, "text" | "color">>,
  now: () => Date,
): Annotation {
  const iso = now().toISOString();
  return {
    id: crypto.randomUUID(),
    type: fields.type,
    page_id: fields.page_id,
    anchor: fields.anchor,
    ...(fields.text !== undefined ? { text: fields.text } : {}),
    ...(fields.color !== undefined ? { color: fields.color } : {}),
    created: iso,
    modified: iso,
    deleted: false,
  };
}

/** The live (non-tombstoned) annotations — what the list and render surfaces show. */
export function liveAnnotations(doc: Annotations): Annotation[] {
  return doc.annotations.filter((a) => !a.deleted);
}

/** Whether `page_id` currently carries a live bookmark. */
export function hasBookmark(doc: Annotations, pageId: string): boolean {
  return doc.annotations.some((a) => a.type === "bookmark" && a.page_id === pageId && !a.deleted);
}

export async function createHighlight(
  storage: Storage,
  bookId: string,
  input: { page_id: string; anchor: Anchor; color: HighlightColor },
  now: () => Date = () => new Date(),
): Promise<Annotations> {
  const doc = await readAnnotations(storage, bookId);
  doc.annotations.push(
    makeAnnotation({ type: "highlight", page_id: input.page_id, anchor: input.anchor, color: input.color }, now),
  );
  return writeDoc(storage, bookId, DEV_USER_ID, doc);
}

export async function createNote(
  storage: Storage,
  bookId: string,
  input: { page_id: string; anchor: Anchor; color: HighlightColor; text: string },
  now: () => Date = () => new Date(),
): Promise<Annotations> {
  const doc = await readAnnotations(storage, bookId);
  doc.annotations.push(
    makeAnnotation(
      { type: "note", page_id: input.page_id, anchor: input.anchor, color: input.color, text: input.text },
      now,
    ),
  );
  return writeDoc(storage, bookId, DEV_USER_ID, doc);
}

export async function updateAnnotation(
  storage: Storage,
  bookId: string,
  id: string,
  patch: { color?: HighlightColor; text?: string },
  now: () => Date = () => new Date(),
): Promise<Annotations> {
  const doc = await readAnnotations(storage, bookId);
  const target = doc.annotations.find((a) => a.id === id);
  if (target) {
    if (patch.color !== undefined) target.color = patch.color;
    if (patch.text !== undefined) target.text = patch.text;
    target.modified = now().toISOString();
  }
  return writeDoc(storage, bookId, DEV_USER_ID, doc);
}

/** Tombstone an annotation: `deleted = true`, `modified` bumped. Idempotent for an already-dead record. */
export async function deleteAnnotation(
  storage: Storage,
  bookId: string,
  id: string,
  now: () => Date = () => new Date(),
): Promise<Annotations> {
  const doc = await readAnnotations(storage, bookId);
  const target = doc.annotations.find((a) => a.id === id);
  if (target && !target.deleted) {
    target.deleted = true;
    target.modified = now().toISOString();
  }
  return writeDoc(storage, bookId, DEV_USER_ID, doc);
}

/** Page-level bookmark toggle: create a `{start:0,end:0}` bookmark, or tombstone the live one. */
export async function toggleBookmark(
  storage: Storage,
  bookId: string,
  pageId: string,
  now: () => Date = () => new Date(),
): Promise<Annotations> {
  const doc = await readAnnotations(storage, bookId);
  const existing = doc.annotations.find(
    (a) => a.type === "bookmark" && a.page_id === pageId && !a.deleted,
  );
  if (existing) {
    existing.deleted = true;
    existing.modified = now().toISOString();
  } else {
    doc.annotations.push(
      makeAnnotation({ type: "bookmark", page_id: pageId, anchor: { start: 0, end: 0 } }, now),
    );
  }
  return writeDoc(storage, bookId, DEV_USER_ID, doc);
}
