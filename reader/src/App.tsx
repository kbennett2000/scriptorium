import { Shelf } from "./shelf/Shelf";

// R1a: the shelf shell — checkout is wired, the reading surface arrives in R1b. Minimal/dense on
// purpose (the designed skin is R4).
export function App() {
  return (
    <main className="app">
      <header className="app-header">
        <h1>Scriptorium</h1>
      </header>
      <Shelf />
    </main>
  );
}
