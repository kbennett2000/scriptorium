import { Fragment, useEffect, useMemo, useRef, useState } from "react";

import type MiniSearch from "minisearch";

import type { BundleReader } from "../readerview/BundleReader";
import type { Storage } from "../shell";
import { ensureIndex, firstMatchIndex, searchPages, snippet, type IndexedPage, type PageHit } from ".";

// The search surface (DESIGN §13): a slide-over panel over the reading surface. It lazily loads (or,
// on first use, builds + persists) the book's MiniSearch index, queries as you type, and lists page
// hits with a snippet. Clicking a hit jumps the reader to that page and flashes the match — the jump
// carries the match's char offset so the reader lands on the right paragraph. Fully local; no network.

const escapeRegExp = (s: string): string => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Render a snippet with the matched terms wrapped in <mark>. */
function SnippetText({ text, terms }: { text: string; terms: string[] }) {
  const s = snippet(text, terms);
  if (!terms.length) return <>{s}</>;
  const re = new RegExp(`(${terms.map(escapeRegExp).join("|")})`, "ig");
  const lower = terms.map((t) => t.toLowerCase());
  return (
    <>
      {s.split(re).map((part, i) =>
        lower.includes(part.toLowerCase()) ? <mark key={i}>{part}</mark> : <Fragment key={i}>{part}</Fragment>,
      )}
    </>
  );
}

export function SearchPanel({
  reader,
  storage,
  bookId,
  pageIds,
  onJump,
  onClose,
}: {
  reader: BundleReader;
  storage: Storage;
  bookId: string;
  pageIds: string[];
  /** Jump to a page (1-based seq) and land near `char` in its text. */
  onJump: (seq: number, char: number) => void;
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [ready, setReady] = useState(false);
  const msRef = useRef<MiniSearch<IndexedPage> | null>(null);

  // Load/build the index once when the panel opens.
  useEffect(() => {
    let live = true;
    void ensureIndex(storage, reader, bookId, pageIds).then((ms) => {
      if (live) {
        msRef.current = ms;
        setReady(true);
      }
    });
    return () => {
      live = false;
    };
  }, [storage, reader, bookId, pageIds]);

  const results = useMemo<PageHit[]>(() => {
    if (!ready || !msRef.current) return [];
    return searchPages(msRef.current, query);
  }, [query, ready]);

  return (
    <section className="search-panel" role="dialog" aria-label="Search">
      <div className="search-bar">
        <input
          className="search-input"
          type="search"
          autoFocus
          placeholder={ready ? "Search this book" : "Building index…"}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search this book"
        />
        <button type="button" className="search-close" aria-label="Close search" onClick={onClose}>
          ×
        </button>
      </div>

      {query.trim() && (
        <p className="search-count">
          {results.length} {results.length === 1 ? "result" : "results"}
        </p>
      )}

      <ul className="search-results">
        {results.map((r) => (
          <li key={r.id}>
            <button
              type="button"
              className="search-result"
              onClick={() => onJump(r.seq, Math.max(0, firstMatchIndex(r.text, r.terms)))}
            >
              <span className="search-result-page">p. {r.seq}</span>
              <span className="search-result-snippet">
                <SnippetText text={r.text} terms={r.terms} />
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
