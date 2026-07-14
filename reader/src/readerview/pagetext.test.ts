import { describe, expect, it, vi } from "vitest";

import page0001 from "../../../server/tests/fixtures/bundle/pages/0001.json";
import page0006 from "../../../server/tests/fixtures/bundle/pages/0006.json";
import {
  joinParagraphs,
  paragraphIndexForChar,
  paragraphStarts,
  splitParagraphs,
  throttle,
  topVisibleChar,
} from "./pagetext";

// THE RENDERING LOCK (DESIGN §13, §6, §5). Byte-faithful paragraph rendering is the substrate R2's
// annotation anchors and R1b's position `char` are UTF-16 offsets into. If any of these break, anchors
// silently corrupt — so this suite is intentionally exhaustive about the split/join round-trip, offset
// math, and verse preservation.

// Fixture pages carry no verse lines, so we add synthetic strings that exercise every edge case.
const VERSE = "Roses are red,\nviolets are blue.\n\nA new stanza\nwith two lines.";
const EDGE_CASES = [
  "",
  "single paragraph, no breaks",
  "a\n\nb\n\nc",
  "\n\nleading blank",
  "trailing blank\n\n",
  "a\n\n\n\nempty middle",
  "odd\n\n\nrun", // triple \n → the extra \n becomes a leading verse break of the next paragraph
  VERSE,
  page0001.text,
  page0006.text,
];

describe("split/join is a byte-exact round-trip", () => {
  it.each(EDGE_CASES)("joinParagraphs(splitParagraphs(t)) === t", (text) => {
    expect(joinParagraphs(splitParagraphs(text))).toBe(text);
  });
});

describe("paragraphStarts indexes the canonical string", () => {
  it.each(EDGE_CASES)("text.slice(start, start+len) === paragraph", (text) => {
    const paras = splitParagraphs(text);
    const starts = paragraphStarts(paras);
    expect(starts).toHaveLength(paras.length);
    paras.forEach((p, i) => {
      expect(text.slice(starts[i], starts[i] + p.length)).toBe(p);
    });
  });

  it("uses the +2 per-delimiter formula (UTF-16 code units)", () => {
    const paras = ["ab", "cde", "f"];
    // 0; 2+2=4; 4+3+2=9
    expect(paragraphStarts(paras)).toEqual([0, 4, 9]);
  });

  it("counts an astral char as 2 UTF-16 units (no code-point iteration)", () => {
    const text = "a\u{1F600}b\n\nnext"; // emoji is a surrogate pair → length 2
    const starts = paragraphStarts(splitParagraphs(text));
    expect(starts).toEqual([0, "a\u{1F600}b".length + 2]);
    expect(starts[1]).toBe(6);
  });
});

describe("verse: lone \\n survives inside a paragraph", () => {
  it("does not split on single newlines", () => {
    const paras = splitParagraphs(VERSE);
    expect(paras).toHaveLength(2);
    expect(paras[0]).toContain("\n");
    expect(paras[0]).toBe("Roses are red,\nviolets are blue.");
  });
});

describe("paragraphIndexForChar (restore path)", () => {
  const starts = [0, 10, 25]; // three paragraphs
  it("finds the paragraph containing an offset", () => {
    expect(paragraphIndexForChar(starts, 0)).toBe(0);
    expect(paragraphIndexForChar(starts, 9)).toBe(0);
    expect(paragraphIndexForChar(starts, 10)).toBe(1);
    expect(paragraphIndexForChar(starts, 24)).toBe(1);
    expect(paragraphIndexForChar(starts, 999)).toBe(2);
  });
  it("clamps a negative offset to 0", () => {
    expect(paragraphIndexForChar(starts, -5)).toBe(0);
    expect(paragraphIndexForChar([], 5)).toBe(0);
  });
});

describe("topVisibleChar (pure, layout-free)", () => {
  const starts = [0, 100, 260, 480];
  const tops = [0, 200, 500, 900];
  it("returns the start char of the last paragraph at/above the scroll top", () => {
    expect(topVisibleChar(starts, tops, 0)).toBe(0);
    expect(topVisibleChar(starts, tops, 199)).toBe(0);
    expect(topVisibleChar(starts, tops, 200)).toBe(100);
    expect(topVisibleChar(starts, tops, 650)).toBe(260);
    expect(topVisibleChar(starts, tops, 5000)).toBe(480);
  });
  it("defaults to char 0 with no layout (jsdom: all tops 0, scrollTop 0)", () => {
    expect(topVisibleChar(starts, [0, 0, 0, 0], 0)).toBe(0);
    expect(topVisibleChar([], [], 0)).toBe(0);
  });
});

describe("throttle", () => {
  it("fires leading immediately and a trailing call for the last args", () => {
    vi.useFakeTimers();
    try {
      const calls: number[] = [];
      const t = throttle((n: number) => calls.push(n), 100);
      t(1); // leading
      t(2);
      t(3); // last args → trailing
      expect(calls).toEqual([1]);
      vi.advanceTimersByTime(100);
      expect(calls).toEqual([1, 3]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("cancel() drops a pending trailing call", () => {
    vi.useFakeTimers();
    try {
      const calls: number[] = [];
      const t = throttle((n: number) => calls.push(n), 100);
      t(1);
      t(2);
      t.cancel();
      vi.advanceTimersByTime(200);
      expect(calls).toEqual([1]);
    } finally {
      vi.useRealTimers();
    }
  });
});
