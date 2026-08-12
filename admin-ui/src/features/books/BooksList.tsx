import { Fragment, useMemo, useState } from "react";

import { getStyles, listBooks } from "../../api/client";
import { ErrorNotice, formatTimestamp, Loading, useAsync } from "../../components/common";
import type { Job } from "../../api/types";
import { navigate } from "../../routes";
import { type BookGroup, groupBooks } from "./group";

// Books screen: the list half of §11.3's "Books" (the New Book wizard is a separate route). A book's
// per-user picture sets (id `{book}#{set_id}`) render as their own jobs, so they're grouped under the
// book and revealed by an expander instead of cluttering the list as bare "(untitled)" rows.
export function BooksList() {
  const { data: books, error, loading } = useAsync(() => listBooks(), []);
  const styles = useAsync(() => getStyles(), []);

  // style_id → display name ("comic-book" → "Comic Book"), falling back to the raw id.
  const styleName = useMemo(() => {
    const map = new Map((styles.data?.styles ?? []).map((s) => [s.id, s.name]));
    return (id: string) => map.get(id) ?? id;
  }, [styles.data]);

  const groups = useMemo(() => groupBooks(books ?? []), [books]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const toggle = (bookId: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(bookId)) next.delete(bookId);
      else next.add(bookId);
      return next;
    });

  return (
    <section>
      <div className="spread">
        <h2>Books</h2>
        <button className="primary" onClick={() => navigate({ name: "wizard" })}>
          New Book
        </button>
      </div>

      {loading && <Loading what="books" />}
      <ErrorNotice error={error} prefix="Could not load books" />

      {books && books.length === 0 && (
        <p className="muted">No books yet. Start one with “New Book”.</p>
      )}

      {groups.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Title</th>
              <th>State</th>
              <th>Warnings</th>
              <th>Failed</th>
              <th>Updated</th>
            </tr>
          </thead>
          <tbody>
            {groups.map((g) => (
              <Fragment key={`book:${g.bookId}`}>
                <BookRow
                  group={g}
                  open={expanded.has(g.bookId)}
                  onToggle={() => toggle(g.bookId)}
                />
                {expanded.has(g.bookId) &&
                  g.sets.map((set) => (
                    <SetRow key={set.id} set={set} styleName={styleName} />
                  ))}
              </Fragment>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function BookRow({
  group,
  open,
  onToggle,
}: {
  group: BookGroup;
  open: boolean;
  onToggle: () => void;
}) {
  const { book, bookId, sets } = group;
  const clickable = book !== null;
  return (
    <tr
      className={clickable ? "clickable" : undefined}
      onClick={clickable ? () => navigate({ name: "detail", id: bookId }) : undefined}
    >
      <td>
        {book ? (
          book.title || <span className="muted">(untitled)</span>
        ) : (
          <span className="muted">(picture sets only)</span>
        )}
        <div className="muted mono" style={{ fontSize: 11 }}>
          {bookId}
        </div>
        {sets.length > 0 && (
          <button
            type="button"
            className="set-toggle"
            aria-expanded={open}
            onClick={(e) => {
              e.stopPropagation();
              onToggle();
            }}
          >
            {open ? "▾" : "▸"} {sets.length} picture set{sets.length === 1 ? "" : "s"}
          </button>
        )}
      </td>
      <td>{book && <span className="badge state">{book.state}</span>}</td>
      <td>{book ? book.warnings.length || "" : ""}</td>
      <td>{book ? book.failed_units.length || "" : ""}</td>
      <td className="muted">{book ? formatTimestamp(book.updated_at) : ""}</td>
    </tr>
  );
}

// A friendlier word for the set lifecycle states than the raw job state.
function setStateLabel(state: string): string {
  if (state === "set_rendering") return "making pictures";
  if (state === "set_done") return "ready";
  return state;
}

function SetRow({ set, styleName }: { set: Job; styleName: (id: string) => string }) {
  const styleId = String(set.bake_config.style_id ?? "");
  const kind = String(set.source.kind ?? "");
  const name = styleName(styleId);
  const label = kind === "reroll" ? `${name} (re-roll)` : name;
  const setId = String(set.source.set_id ?? set.id);
  return (
    <tr className="set-subrow">
      <td>
        <span className="set-name">{label}</span>
        <div className="muted mono" style={{ fontSize: 11 }}>
          {setId}
        </div>
      </td>
      <td>
        <span className="badge state">{setStateLabel(set.state)}</span>
      </td>
      <td></td>
      <td></td>
      <td className="muted">{formatTimestamp(set.updated_at)}</td>
    </tr>
  );
}
