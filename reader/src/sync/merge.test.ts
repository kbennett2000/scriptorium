import { describe, expect, it } from "vitest";

import type { Annotations, Positions } from "@scriptorium/shared";

import vectors from "../../../shared/test-vectors/sync-merge.json";
import { canonicalJson, mergeAnnotations, mergePositions } from "./merge";

// The TypeScript half of the shared sync-merge contract. The SAME vector file drives the Python suite
// (server/tests/test_sync_vectors.py); if this port drifts from sync/merge.py, one of the two reddens.
// Every case is run in BOTH orders to pin commutativity — two devices may reconnect in either order.

interface AnnCase {
  name: string;
  a: Annotations;
  b: Annotations;
  expected: Annotations;
}
interface PosCase {
  name: string;
  a: Positions;
  b: Positions;
  expected: Positions;
}

const v = vectors as { annotations: AnnCase[]; positions: PosCase[] };

describe("shared sync-merge vectors — annotations", () => {
  for (const c of v.annotations) {
    it(`${c.name} (a,b)`, () => {
      expect(mergeAnnotations(c.a, c.b)).toEqual(c.expected);
    });
    it(`${c.name} (b,a) — commutative`, () => {
      expect(mergeAnnotations(c.b, c.a)).toEqual(c.expected);
    });
  }
});

describe("shared sync-merge vectors — positions", () => {
  for (const c of v.positions) {
    it(`${c.name} (a,b)`, () => {
      expect(mergePositions(c.a, c.b)).toEqual(c.expected);
    });
    it(`${c.name} (b,a) — commutative`, () => {
      expect(mergePositions(c.b, c.a)).toEqual(c.expected);
    });
  }
});

describe("canonicalJson mirrors Python json.dumps(sort_keys=True, ensure_ascii=False)", () => {
  it("sorts keys and uses '\", \"' / '\": \"' separators", () => {
    expect(canonicalJson({ b: 1, a: 2 })).toBe('{"a": 2, "b": 1}');
    expect(canonicalJson({ anchor: { end: 5, start: 0 }, id: "x" })).toBe(
      '{"anchor": {"end": 5, "start": 0}, "id": "x"}',
    );
  });
  it("leaves non-ASCII raw (does not escape)", () => {
    expect(canonicalJson({ text: "café" })).toBe('{"text": "café"}');
  });
});
