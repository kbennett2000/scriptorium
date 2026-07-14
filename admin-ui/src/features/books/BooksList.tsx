import { listBooks } from "../../api/client";
import { ErrorNotice, Loading, useAsync } from "../../components/common";
import { navigate } from "../../routes";

// Books screen: the list half of §11.3's "Books" (the New Book wizard is a separate route).
export function BooksList() {
  const { data: books, error, loading } = useAsync(() => listBooks(), []);

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

      {books && books.length > 0 && (
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
            {books.map((b) => (
              <tr
                key={b.book_id}
                className="clickable"
                onClick={() => navigate({ name: "detail", id: b.book_id })}
              >
                <td>
                  {b.title || <span className="muted">(untitled)</span>}
                  <div className="muted mono" style={{ fontSize: 11 }}>
                    {b.book_id}
                  </div>
                </td>
                <td>
                  <span className="badge state">{b.state}</span>
                </td>
                <td>{b.warnings.length || ""}</td>
                <td>{b.failed_units.length || ""}</td>
                <td className="muted">{b.updated_at.replace("T", " ").slice(0, 19)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
