#!/usr/bin/env node
// R4 build guard (DESIGN §13, ADR-0003 — zero-online read path). After `vite build`, prove the
// production bundle vendors its fonts and pulls NOTHING from a CDN:
//   1. dist/ must contain at least one .woff2 (the vendored Literata/Inter faces landed in the build).
//   2. No text asset may reference an external font/CDN host (`fonts.googleapis` or `cdn`) — the same
//      grep the cycle spec calls for, run in-process so CI fails loud instead of a manual check.
// Exit non-zero on any violation. Run via `npm run build:check` (build + this guard).

import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const DIST = resolve(dirname(fileURLToPath(import.meta.url)), "..", "dist");
const FORBIDDEN = [/fonts\.googleapis/i, /cdn/i];
// Only text assets can carry an external URL; woff2/webp/png are binary and never grepped.
const TEXT_EXT = /\.(html|css|js|mjs|json|map|svg|txt|webmanifest)$/i;

function walk(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...walk(p));
    else out.push(p);
  }
  return out;
}

let files;
try {
  files = walk(DIST);
} catch {
  console.error(`check-dist-fonts: no dist/ at ${DIST} — run \`vite build\` first.`);
  process.exit(1);
}

const woff2 = files.filter((f) => f.toLowerCase().endsWith(".woff2"));
const violations = [];
for (const f of files) {
  if (!TEXT_EXT.test(f)) continue;
  const text = readFileSync(f, "utf8");
  for (const re of FORBIDDEN) {
    if (re.test(text)) violations.push(`${f} matches ${re}`);
  }
}

let ok = true;
if (woff2.length === 0) {
  console.error("check-dist-fonts: FAIL — no .woff2 in dist/ (fonts not vendored into the build).");
  ok = false;
} else {
  console.log(`check-dist-fonts: ${woff2.length} vendored .woff2 in dist/ ✓`);
}
if (violations.length) {
  console.error("check-dist-fonts: FAIL — external font/CDN reference(s) in the bundle:");
  for (const v of violations) console.error(`  ${v}`);
  ok = false;
} else {
  console.log("check-dist-fonts: no fonts.googleapis / cdn references ✓");
}

process.exit(ok ? 0 : 1);
