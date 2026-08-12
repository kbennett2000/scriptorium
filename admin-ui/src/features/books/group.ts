import type { Job } from "../../api/types";

// The admin books list mixes real book jobs with per-set render jobs (id `{book}#{set_id}`, states
// set_rendering/set_done — see server artsets/service.py). This groups them so the Books table shows
// one row per book, with its picture sets nested underneath. Pure + presentational; no fetching here.

export interface BookGroup {
  bookId: string;
  /** The book's own job, or null for an orphan set whose book job isn't in the list. */
  book: Job | null;
  /** The book's picture-set jobs, in the order they arrived (created_at). */
  sets: Job[];
}

/** A set job is the only kind whose id carries a `#` ({book}#{set_id}); a book job's id is its book_id. */
export function isSetJob(job: Job): boolean {
  return job.id.includes("#");
}

/** Most recent activity across a group's book + sets — used to sort newest book first. */
function groupUpdatedAt(g: BookGroup): string {
  return [g.book?.updated_at, ...g.sets.map((s) => s.updated_at)]
    .filter((t): t is string => !!t)
    .reduce((a, b) => (a > b ? a : b), "");
}

export function groupBooks(jobs: Job[]): BookGroup[] {
  const groups = new Map<string, BookGroup>();
  const of = (bookId: string): BookGroup => {
    let g = groups.get(bookId);
    if (!g) {
      g = { bookId, book: null, sets: [] };
      groups.set(bookId, g);
    }
    return g;
  };

  for (const job of jobs) {
    if (isSetJob(job)) of(job.book_id).sets.push(job);
    else of(job.book_id).book = job;
  }

  return [...groups.values()].sort((a, b) => (groupUpdatedAt(a) > groupUpdatedAt(b) ? -1 : 1));
}
