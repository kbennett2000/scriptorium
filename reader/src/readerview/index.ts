// The reading surface's public surface (DESIGN §13). NOTE: FixtureBundleReader is intentionally NOT
// re-exported here — it evaluates an eager `import.meta.glob` of the fixture bundle, so App loads it
// via dynamic import only when VITE_FIXTURE_BUNDLE is set, keeping the fixtures out of the prod bundle.

export { Reader } from "./Reader";
export type { BundleReader } from "./BundleReader";
export { StorageBundleReader } from "./BundleReader";
