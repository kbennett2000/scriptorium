import type { Meta } from "@scriptorium/shared";

// S1 scaffold only. The real reader (shell, shelf, reading surface, annotations,
// sync, search, settings) arrives across cycles R1–R5. This stub exists to prove
// the build, the shared-types wiring, and lint/typecheck are green.
export function App() {
  const bundleVersion: Meta["bundle_version"] = 1;
  return (
    <main>
      <h1>Scriptorium</h1>
      <p>Reader scaffold — bundle format v{bundleVersion}.</p>
    </main>
  );
}
