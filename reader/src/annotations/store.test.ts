import { describe, expect, it } from "vitest";

import { MemoryStorage } from "../shell";
import {
  DEV_USER_ID,
  createHighlight,
  createNote,
  deleteAnnotation,
  hasBookmark,
  liveAnnotations,
  readAnnotations,
  toggleBookmark,
  updateAnnotation,
} from "./store";

// Local annotation persistence: the wire shape (uuid / ISO / tombstone), the {user}/{book} path, and
// the LWW-friendly delete-as-tombstone semantics (no resurrect on reload).

const BOOK = "usr-0123456789ab";
const at = (iso: string) => () => new Date(iso);
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

describe("annotation store", () => {
  it("starts empty and writes to annotations/{user}/{book}.json", async () => {
    const s = new MemoryStorage();
    expect(await readAnnotations(s, BOOK)).toEqual({
      book_id: BOOK,
      user_id: DEV_USER_ID,
      annotations: [],
    });
    await createHighlight(
      s,
      BOOK,
      { page_id: "0007", anchor: { start: 120, end: 188 }, color: "yellow" },
      at("2026-07-14T00:00:00.000Z"),
    );
    expect(await s.exists(`annotations/default/${BOOK}.json`)).toBe(true);
  });

  it("creates a highlight in the wire shape", async () => {
    const s = new MemoryStorage();
    const doc = await createHighlight(
      s,
      BOOK,
      { page_id: "0007", anchor: { start: 1, end: 5 }, color: "blue" },
      at("2026-07-14T00:00:00.000Z"),
    );
    const a = doc.annotations[0];
    expect(a.type).toBe("highlight");
    expect(a.color).toBe("blue");
    expect(a.page_id).toBe("0007");
    expect(a.anchor).toEqual({ start: 1, end: 5 });
    expect(a.deleted).toBe(false);
    expect(a.created).toBe("2026-07-14T00:00:00.000Z");
    expect(a.modified).toBe(a.created);
    expect(a.id).toMatch(UUID);
    expect(a.text).toBeUndefined(); // highlights have no text
  });

  it("a note carries its text", async () => {
    const s = new MemoryStorage();
    const doc = await createNote(s, BOOK, {
      page_id: "0001",
      anchor: { start: 0, end: 3 },
      color: "green",
      text: "a thought",
    });
    expect(doc.annotations[0].type).toBe("note");
    expect(doc.annotations[0].text).toBe("a thought");
    expect(doc.annotations[0].color).toBe("green");
  });

  it("update bumps modified and keeps created", async () => {
    const s = new MemoryStorage();
    const created = await createHighlight(
      s,
      BOOK,
      { page_id: "0001", anchor: { start: 0, end: 3 }, color: "yellow" },
      at("2026-07-14T00:00:00.000Z"),
    );
    const id = created.annotations[0].id;
    const doc = await updateAnnotation(s, BOOK, id, { color: "pink" }, at("2026-07-15T00:00:00.000Z"));
    expect(doc.annotations[0].color).toBe("pink");
    expect(doc.annotations[0].created).toBe("2026-07-14T00:00:00.000Z");
    expect(doc.annotations[0].modified).toBe("2026-07-15T00:00:00.000Z");
  });

  it("delete writes a tombstone; live view drops it; no resurrect on reload", async () => {
    const s = new MemoryStorage();
    const created = await createHighlight(
      s,
      BOOK,
      { page_id: "0001", anchor: { start: 0, end: 3 }, color: "yellow" },
      at("2026-07-14T00:00:00.000Z"),
    );
    const id = created.annotations[0].id;
    await deleteAnnotation(s, BOOK, id, at("2026-07-16T00:00:00.000Z"));

    const reloaded = await readAnnotations(s, BOOK);
    expect(reloaded.annotations).toHaveLength(1); // tombstone kept for LWW
    expect(reloaded.annotations[0].deleted).toBe(true);
    expect(reloaded.annotations[0].modified).toBe("2026-07-16T00:00:00.000Z");
    expect(liveAnnotations(reloaded)).toHaveLength(0);
  });

  it("toggleBookmark creates a {0,0} bookmark, tombstones it, then re-creates", async () => {
    const s = new MemoryStorage();
    let doc = await toggleBookmark(s, BOOK, "0003");
    expect(hasBookmark(doc, "0003")).toBe(true);
    const bm = doc.annotations[0];
    expect(bm.type).toBe("bookmark");
    expect(bm.anchor).toEqual({ start: 0, end: 0 });
    expect(bm.color).toBeUndefined();

    doc = await toggleBookmark(s, BOOK, "0003");
    expect(hasBookmark(doc, "0003")).toBe(false);
    expect(doc.annotations).toHaveLength(1); // still one record — a tombstone
    expect(doc.annotations[0].deleted).toBe(true);

    doc = await toggleBookmark(s, BOOK, "0003");
    expect(hasBookmark(doc, "0003")).toBe(true);
    expect(doc.annotations).toHaveLength(2); // a fresh live bookmark alongside the tombstone
  });

  it("recovers from a corrupt file with a fresh empty doc", async () => {
    const s = new MemoryStorage();
    await s.writeText(`annotations/default/${BOOK}.json`, "{not json");
    const doc = await readAnnotations(s, BOOK);
    expect(doc.annotations).toEqual([]);
    expect(doc.book_id).toBe(BOOK);
  });
});
