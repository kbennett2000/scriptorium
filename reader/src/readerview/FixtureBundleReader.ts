import type { BundleReader } from "./BundleReader";

// The `VITE_FIXTURE_BUNDLE=1` dev read source: the reading surface with NO scriptorium backend. It
// reads the canonical server fixture bundle (server/tests/fixtures/bundle/) — one source of truth, no
// reader-side copy to drift — bound at build time via `import.meta.glob`:
//   - JSON as raw strings (`?raw`) → inlined into this chunk, parsed on demand.
//   - reader images (images/web/**, images/thumbs/**, `?inline`) → a local asset URL Vite emits into
//     the bundle (small ones may inline as a data: URL), used directly as <img src>. Either way it is
//     a same-origin static asset, never a backend call.
// No `fetch`/XHR is issued — everything is a static import bound by Vite — so the ESLint
// network-boundary fence is not tripped and this module lives happily in readerview/. (The genuinely
// zero-network read path is StorageBundleReader over OPFS; this is a dev convenience.) Crossing into
// the server package needs a `server.fs.allow` entry in vite.config for the dev server (build reads
// from disk directly). Kept in its own module + dynamically imported so the eager glob only evaluates
// in fixture-mode paths.

const FIXTURE_ROOT = "server/tests/fixtures/bundle/";

const jsonModules = import.meta.glob("../../../server/tests/fixtures/bundle/**/*.json", {
  eager: true,
  query: "?raw",
  import: "default",
}) as Record<string, string>;

const imageModules = import.meta.glob(
  "../../../server/tests/fixtures/bundle/images/{web,thumbs}/**/*.webp",
  { eager: true, query: "?inline", import: "default" },
) as Record<string, string>;

/** Reduce a glob key like "../../../server/tests/fixtures/bundle/pages/0001.json" to "pages/0001.json". */
function toRelPath(globKey: string): string {
  const at = globKey.indexOf(FIXTURE_ROOT);
  return at >= 0 ? globKey.slice(at + FIXTURE_ROOT.length) : globKey;
}

const jsonByPath = new Map(Object.entries(jsonModules).map(([k, v]) => [toRelPath(k), v]));
const imageByPath = new Map(Object.entries(imageModules).map(([k, v]) => [toRelPath(k), v]));

/** The fixture book id, exposed so App can open it directly in fixture mode without a shelf fetch. */
export const FIXTURE_BOOK_ID = "usr-ce8f5ebd29d0";

export class FixtureBundleReader implements BundleReader {
  async readJson<T>(relPath: string): Promise<T> {
    const raw = jsonByPath.get(relPath);
    if (raw === undefined) throw new Error(`fixture bundle missing: ${relPath}`);
    return JSON.parse(raw) as T;
  }

  async imageUrl(relPath: string): Promise<string | null> {
    // The current fixture has no `-rN` variants, so a plain path lookup is exact; if a variant fixture
    // is ever added, run resolveReaderFiles over the fixture manifest here (see StorageBundleReader).
    return imageByPath.get(relPath) ?? null;
  }

  dispose(): void {
    // data: URLs need no revocation.
  }
}
