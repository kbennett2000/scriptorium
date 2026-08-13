import "./index.css";

import { BooksList } from "./features/books/BooksList";
import { NewBookWizard } from "./features/books/NewBookWizard";
import { BookDetail } from "./features/detail/BookDetail";
import { PortraitReview } from "./features/portraits/PortraitReview";
import { PostRender } from "./features/postrender/PostRender";
import { CastReview } from "./features/review/CastReview";
import { ReviewGate } from "./features/review/ReviewGate";
import { navigate, useRoute } from "./routes";

// The admin workbench shell: a top bar + hash-routed screen. Deliberately flat — one screen
// component per §11.3 destination, wired to the real /api/admin endpoints via src/api.
export function App() {
  const route = useRoute();
  return (
    <>
      <header className="topbar">
        <h1>Scriptorium Admin</h1>
        <nav>
          <a onClick={() => navigate({ name: "list" })}>Books</a>
          <a onClick={() => navigate({ name: "wizard" })}>New Book</a>
          {/* Back to the reading app — the reader and admin are two screens on the same address. */}
          <a href="/">Library →</a>
        </nav>
      </header>
      <main>
        {route.name === "list" && <BooksList />}
        {route.name === "wizard" && <NewBookWizard />}
        {route.name === "detail" && <BookDetail id={route.id} />}
        {route.name === "castreview" && <CastReview id={route.id} />}
        {route.name === "review" && <ReviewGate id={route.id} />}
        {route.name === "portraits" && <PortraitReview id={route.id} />}
        {route.name === "postrender" && <PostRender id={route.id} />}
      </main>
    </>
  );
}
