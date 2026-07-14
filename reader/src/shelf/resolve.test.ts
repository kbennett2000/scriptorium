import { describe, expect, it } from "vitest";

import type { Manifest } from "@scriptorium/shared";

import vectors from "../../../shared/test-vectors/rn-resolution.json";
import { matchesAny, resolveReaderFiles, resolvedTotalBytes } from "./resolve";

// The TypeScript half of the shared `-rN` contract. The SAME vector file drives the Python suite
// (server/tests/test_rn_vectors.py); if this port drifts from checkout.py, one of the two goes red.

interface VectorCase {
  name: string;
  manifest: Pick<Manifest, "reader_required" | "files">;
  expected: string[];
  expected_total_bytes?: number;
}

function asManifest(m: VectorCase["manifest"]): Manifest {
  return { book_id: "usr-000000000000", revision: 1, bundle_version: 1, total_bytes_reader: 0, ...m };
}

describe("shared -rN resolution vectors", () => {
  for (const c of (vectors as { cases: VectorCase[] }).cases) {
    it(c.name, () => {
      const manifest = asManifest(c.manifest);
      expect(resolveReaderFiles(manifest).map((e) => e.path)).toEqual(c.expected);
      if (c.expected_total_bytes !== undefined) {
        expect(resolvedTotalBytes(manifest)).toBe(c.expected_total_bytes);
      }
    });
  }
});

describe("matchesAny glob dialect", () => {
  it("handles /**, /* (single-segment), and exact", () => {
    expect(matchesAny("pages/0001.json", ["pages/*"])).toBe(true);
    expect(matchesAny("pages/sub/x.json", ["pages/*"])).toBe(false);
    expect(matchesAny("images/web/plates/0001.webp", ["images/web/**"])).toBe(true);
    expect(matchesAny("meta.json", ["meta.json"])).toBe(true);
    expect(matchesAny("images/plates/0001.png", ["images/web/**", "images/thumbs/**"])).toBe(false);
  });
});
