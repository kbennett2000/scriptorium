import type { Styles } from "@scriptorium/shared";

// S1 scaffold only. The real admin workbench (New Book wizard, book detail, the
// review gate) arrives in cycle S9. This stub proves the build, the shared-types
// wiring, and lint/typecheck are green.
export function App() {
  const styleCount: Styles["styles"] = [];
  return (
    <main>
      <h1>Scriptorium Admin</h1>
      <p>Admin scaffold — {styleCount.length} styles loaded.</p>
    </main>
  );
}
