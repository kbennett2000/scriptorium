import { describe, expect, it } from "vitest";

import type { Job } from "../../api/types";
import { groupBooks, isSetJob } from "./group";

// Grouping the flat job list into books-with-their-picture-sets (server emits set jobs as `{book}#{id}`).

function mkJob(id: string, overrides: Partial<Job> = {}): Job {
  const bookId = id.includes("#") ? id.split("#")[0] : id;
  return {
    id,
    book_id: bookId,
    state: "published",
    source: {},
    bake_config: {},
    title: null,
    warnings: [],
    prompt_warnings: {},
    render_stub: false,
    failed_units: [],
    prev_state: null,
    started: true,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    ...overrides,
  };
}

describe("isSetJob", () => {
  it("treats a `{book}#{set}` id as a set, a plain book id as a book", () => {
    expect(isSetJob(mkJob("usr-aaaaaaaaaaaa#set-b4d8746db3fc"))).toBe(true);
    expect(isSetJob(mkJob("usr-aaaaaaaaaaaa"))).toBe(false);
  });
});

describe("groupBooks", () => {
  it("nests a book's set jobs under it and keeps other books separate", () => {
    const book = mkJob("usr-aaaaaaaaaaaa", { title: "Ted's Trip", updated_at: "2026-08-02T00:00:00Z" });
    const setA = mkJob("usr-aaaaaaaaaaaa#set-aaaaaaaaaaaa", { state: "set_done" });
    const setB = mkJob("usr-aaaaaaaaaaaa#set-bbbbbbbbbbbb", { state: "set_rendering" });
    const other = mkJob("pg-42");

    const groups = groupBooks([book, setA, setB, other]);

    const ted = groups.find((g) => g.bookId === "usr-aaaaaaaaaaaa")!;
    expect(ted.book).toBe(book);
    expect(ted.sets).toEqual([setA, setB]);

    const pg = groups.find((g) => g.bookId === "pg-42")!;
    expect(pg.book).toBe(other);
    expect(pg.sets).toEqual([]);
  });

  it("makes a group with book=null for an orphan set (no matching book job)", () => {
    const orphan = mkJob("usr-cccccccccccc#set-dddddddddddd", { state: "set_rendering" });
    const groups = groupBooks([orphan]);
    expect(groups).toHaveLength(1);
    expect(groups[0].book).toBeNull();
    expect(groups[0].sets).toEqual([orphan]);
  });

  it("sorts groups by most-recent activity, newest first", () => {
    const oldBook = mkJob("pg-1", { updated_at: "2026-08-01T00:00:00Z" });
    const newBook = mkJob("pg-2", { updated_at: "2026-08-05T00:00:00Z" });
    const groups = groupBooks([oldBook, newBook]);
    expect(groups.map((g) => g.bookId)).toEqual(["pg-2", "pg-1"]);
  });
});
