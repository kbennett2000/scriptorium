import MiniSearch, { type Options } from "minisearch";

import type { BundleReader } from "../readerview/BundleReader";
import type { Storage } from "../shell";

// Full-text search (DESIGN §13, ADR-0006). A MiniSearch index over `{id, seq, text}` — one document
// per logical page — is built at checkout completion (see shelf/checkout.ts) and persisted via
// `toJSON` to `books/{bookId}/search-index.json`, then lazily loaded when the reader opens search.
// Already-Resident books (and the fixture, which never checks out) build the index on first search
// via `ensureIndex`. Everything here is LOCAL: it reads page text through the injected BundleReader /
// Storage and mints no network I/O, so it lives happily outside the shelf/+sync/ network fence.
//
// The persisted form is deterministic (MiniSearch.toJSON), so reload → load-from-disk → search returns
// results with NO rebuild (proven by `buildCount()` staying flat across a reload — see r4.spec / tests).

/** A page as indexed: id (4-digit), 1-based seq, and the byte-faithful page text (also stored for snippets). */
export interface IndexedPage {
  id: string;
  seq: number;
  text: string;
}

/** One search hit: the page it matched, the matched document terms, and the page text (for snippets). */
export interface PageHit {
  id: string;
  seq: number;
  terms: string[];
  text: string;
}

// The index options are a single shared const: `buildIndex` and `deserializeIndex` MUST agree on them
// or a loaded index behaves differently from a freshly built one. `text` is stored so hits carry the
// page text for snippet rendering without a second read.
const OPTIONS: Options<IndexedPage> = {
  idField: "id",
  fields: ["text"],
  storeFields: ["id", "seq", "text"],
};

// Test/e2e probe: counts REAL index builds (not loads). A reload that loads from disk must not bump it.
let builds = 0;
export function buildCount(): number {
  return builds;
}

/** Build an in-memory index from page docs. Increments the build counter (see `buildCount`). */
export function buildIndex(pages: IndexedPage[]): MiniSearch<IndexedPage> {
  const ms = new MiniSearch<IndexedPage>(OPTIONS);
  ms.addAll(pages);
  builds += 1;
  if (typeof window !== "undefined") {
    (window as unknown as { __searchBuildCount?: number }).__searchBuildCount = builds;
  }
  return ms;
}

export function serializeIndex(ms: MiniSearch<IndexedPage>): string {
  return JSON.stringify(ms.toJSON());
}

export function deserializeIndex(json: string): MiniSearch<IndexedPage> {
  return MiniSearch.loadJSON<IndexedPage>(json, OPTIONS);
}

/** Bundle-relative storage path for a book's persisted index (co-located; shelf `remove` wipes it). */
export function indexPath(bookId: string): string {
  return `books/${bookId}/search-index.json`;
}

/** Query the index. Empty/whitespace query → no results. Prefix + light fuzzy for a novel-reader feel. */
export function searchPages(ms: MiniSearch<IndexedPage>, query: string): PageHit[] {
  const q = query.trim();
  if (!q) return [];
  return ms.search(q, { prefix: true, fuzzy: 0.2 }).map((r) => ({
    id: String(r.id),
    seq: Number(r.seq),
    terms: r.terms,
    text: String(r.text ?? ""),
  }));
}

/**
 * Return the book's index: load the persisted one if present (no rebuild), else build it from the
 * bundle's pages (via the reader), persist it, and return it. This is the build-on-first-search
 * migration path for books that were Resident before search shipped, and the only path in fixture mode.
 */
export async function ensureIndex(
  storage: Storage,
  reader: BundleReader,
  bookId: string,
  pageIds: string[],
): Promise<MiniSearch<IndexedPage>> {
  const path = indexPath(bookId);
  if (await storage.exists(path)) {
    try {
      return deserializeIndex(await storage.readText(path));
    } catch {
      // Corrupt/incompatible persisted index — fall through and rebuild.
    }
  }
  const pages = await Promise.all(
    pageIds.map(async (id) => {
      const p = await reader.readJson<IndexedPage>(`pages/${id}.json`);
      return { id: p.id, seq: p.seq, text: p.text };
    }),
  );
  const ms = buildIndex(pages);
  await storage.writeText(path, serializeIndex(ms));
  return ms;
}

/**
 * Build and persist a book's index straight from its Resident page files in Storage. Called at
 * checkout completion / delta (shelf/checkout.ts), where a BundleReader isn't constructed yet.
 */
export async function buildAndPersistIndexFromStorage(storage: Storage, bookId: string): Promise<void> {
  const prefix = `books/${bookId}/pages/`;
  const files = (await storage.list(prefix)).filter((p) => p.endsWith(".json"));
  const pages = await Promise.all(
    files.map(async (f) => {
      const p = JSON.parse(await storage.readText(f)) as IndexedPage;
      return { id: p.id, seq: p.seq, text: p.text };
    }),
  );
  await storage.writeText(indexPath(bookId), serializeIndex(buildIndex(pages)));
}

const SNIPPET_RADIUS = 60;

/** A ~120-char window of `text` centered on the first matching term, ellipsized. Plain text. */
export function snippet(text: string, terms: string[]): string {
  const at = firstMatchIndex(text, terms);
  if (at < 0) return text.slice(0, SNIPPET_RADIUS * 2).trim();
  const start = Math.max(0, at - SNIPPET_RADIUS);
  const end = Math.min(text.length, at + SNIPPET_RADIUS);
  const core = text.slice(start, end).replace(/\s+/g, " ").trim();
  return `${start > 0 ? "…" : ""}${core}${end < text.length ? "…" : ""}`;
}

/** Index of the earliest occurrence of any term in `text` (case-insensitive), or -1. */
export function firstMatchIndex(text: string, terms: string[]): number {
  const hay = text.toLowerCase();
  let best = -1;
  for (const t of terms) {
    const i = hay.indexOf(t.toLowerCase());
    if (i >= 0 && (best < 0 || i < best)) best = i;
  }
  return best;
}
