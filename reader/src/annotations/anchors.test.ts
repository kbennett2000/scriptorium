import { afterEach, describe, expect, it } from "vitest";

import page0001 from "../../../server/tests/fixtures/bundle/pages/0001.json";
import page0006 from "../../../server/tests/fixtures/bundle/pages/0006.json";
import { paragraphStarts, splitParagraphs } from "../readerview/pagetext";
import { anchorToDomRange, domRangeToAnchor } from "./anchors";
import { paintParagraph, type Span } from "./segments";

// THE load-bearing suite (BUILD-PLAN R2): the anchor round-trip is exact over hundreds of random
// ranges, across paragraph edges, verse "\n", and astral (surrogate-pair) characters. Ranges are built
// against a DOM that mirrors Page.tsx exactly (`.page-text > p.page-para`, one text node per paragraph),
// and — for the segmented case — the same DOM after highlight spans have subdivided the paragraphs.

// The canonical text has "\n\n" BETWEEN paragraphs, but those join characters are structural and never
// appear in the DOM. So the round-trip invariant is stated over DOM ranges: reconstructing a selection
// from its anchor selects character-identical text to the original selection (both lack the join chars).

// --- deterministic PRNG (mulberry32); no fast-check dependency in this repo ---
function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Build the exact DOM Page.tsx renders with no highlights: one text node per paragraph. */
function buildPageDom(text: string): HTMLElement {
  const container = document.createElement("div");
  container.className = "page-text";
  for (const para of splitParagraphs(text)) {
    const p = document.createElement("p");
    p.className = "page-para";
    if (para.length) p.appendChild(document.createTextNode(para)); // React omits an empty-string child
    container.appendChild(p);
  }
  document.body.appendChild(container);
  return container;
}

/** Build the DOM Page.tsx renders WITH highlights: paragraphs subdivided into spans + bare text. */
function buildSegmentedDom(text: string, spans: Span[]): HTMLElement {
  const container = document.createElement("div");
  container.className = "page-text";
  const paras = splitParagraphs(text);
  const starts = paragraphStarts(paras);
  paras.forEach((para, i) => {
    const p = document.createElement("p");
    p.className = "page-para";
    for (const run of paintParagraph(para, starts[i], spans)) {
      if (run.color) {
        const span = document.createElement("span");
        span.className = `hl hl-${run.color}`;
        span.appendChild(document.createTextNode(run.text));
        p.appendChild(span);
      } else {
        p.appendChild(document.createTextNode(run.text));
      }
    }
    container.appendChild(p);
  });
  document.body.appendChild(container);
  return container;
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("anchors round-trip (property)", () => {
  const PAGES: Record<string, string> = {
    "fixture-0001": page0001.text,
    "fixture-0006": page0006.text,
    verse: "Roses are red,\nviolets are blue.\n\nA new stanza\nwith two lines.\n\nAnd a third.",
    "multi-para": "First paragraph here.\n\nSecond one.\n\nThird and final paragraph of the page.",
  };

  it("reconstructs 500+ random selections character-identically (incl. cross-paragraph & verse)", () => {
    const SEED = 0x1a2b3c4d; // logged below for reproducibility
    const N = 600;
    const prng = mulberry32(SEED);
    const names = Object.keys(PAGES);
    let crossPara = 0;
    let checked = 0;

    for (let iter = 0; iter < N; iter++) {
      const name = names[Math.floor(prng() * names.length)];
      const text = PAGES[name];
      const container = buildPageDom(text);
      const nodes = [...container.querySelectorAll<HTMLElement>(".page-para")]
        .map((p) => p.firstChild as Text | null)
        .filter((t): t is Text => t != null && t.length > 0);
      if (nodes.length === 0) {
        container.remove();
        continue;
      }

      let i = Math.floor(prng() * nodes.length);
      let j = Math.floor(prng() * nodes.length);
      if (i > j) [i, j] = [j, i];
      let oi = Math.floor(prng() * (nodes[i].length + 1));
      let oj = Math.floor(prng() * (nodes[j].length + 1));
      if (i === j) {
        if (oi === oj) {
          container.remove();
          continue;
        }
        if (oi > oj) [oi, oj] = [oj, oi];
      }

      const range = document.createRange();
      range.setStart(nodes[i], oi);
      range.setEnd(nodes[j], oj);

      const anchor = domRangeToAnchor(range, container, text);
      expect(anchor).not.toBeNull();
      if (!anchor) {
        container.remove();
        continue;
      }
      const rebuilt = anchorToDomRange(anchor, container, text);
      expect(rebuilt).not.toBeNull();

      // Character-identical reconstruction, and a stable anchor when read back from the rebuilt range.
      expect(rebuilt?.toString()).toBe(range.toString());
      expect(domRangeToAnchor(rebuilt as Range, container, text)).toEqual(anchor);

      if (i !== j) crossPara++;
      checked++;
      container.remove();
    }

    // Guard the test actually exercised the hard cases (fail loudly if the generator degenerates).
    expect(checked).toBeGreaterThanOrEqual(500);
    expect(crossPara).toBeGreaterThan(0);
    console.log(`anchors round-trip: seed=${SEED} checked=${checked} cross-paragraph=${crossPara}`);
  });

  it("resolves identical text on a segmented (highlighted) DOM as on a plain DOM", () => {
    const text = page0001.text;
    const spans: Span[] = [
      { id: "a", start: 12, end: 44, color: "yellow" },
      { id: "b", start: 30, end: 70, color: "blue" }, // overlaps a → forces multi-node paragraphs
    ];
    const plain = buildPageDom(text);
    const seg = buildSegmentedDom(text, spans);
    const prng = mulberry32(99);
    const len = text.length;

    for (let k = 0; k < 200; k++) {
      let s = Math.floor(prng() * (len + 1));
      let e = Math.floor(prng() * (len + 1));
      if (s > e) [s, e] = [e, s];
      if (s === e) continue;
      const anchor = { start: s, end: e };
      const rp = anchorToDomRange(anchor, plain, text);
      const rs = anchorToDomRange(anchor, seg, text);
      // The segmentation must be invisible to anchoring: same selected text, same read-back anchor.
      expect(rs?.toString()).toBe(rp?.toString());
      expect(domRangeToAnchor(rs as Range, seg, text)).toEqual(
        domRangeToAnchor(rp as Range, plain, text),
      );
    }
  });
});

describe("anchors edge cases", () => {
  it("counts an astral character as 2 UTF-16 units and never bisects the pair", () => {
    const text = "Emoji \u{1F600} tail\n\nsecond \u{1D510} line"; // 😀 and 𝔐 are surrogate pairs
    const container = buildPageDom(text);
    const para0 = container.querySelectorAll<HTMLElement>(".page-para")[0].firstChild as Text;

    // "Emoji " is 6 code units; the emoji occupies units 6..8.
    const range = document.createRange();
    range.setStart(para0, 6);
    range.setEnd(para0, 8);
    expect(range.toString()).toBe("\u{1F600}");

    const anchor = domRangeToAnchor(range, container, text);
    expect(anchor).toEqual({ start: 6, end: 8 }); // two code units, not one
    const rebuilt = anchorToDomRange(anchor as { start: number; end: number }, container, text);
    expect(rebuilt?.toString()).toBe("\u{1F600}");
  });

  it("round-trips a selection spanning an internal verse newline", () => {
    const text = "Roses are red,\nviolets are blue.";
    const container = buildPageDom(text);
    const node = container.querySelector<HTMLElement>(".page-para")?.firstChild as Text;
    const range = document.createRange();
    range.setStart(node, 10); // inside "red,"
    range.setEnd(node, 22); // inside "violets", crossing the "\n"
    expect(range.toString()).toContain("\n");
    const anchor = domRangeToAnchor(range, container, text);
    const rebuilt = anchorToDomRange(anchor as { start: number; end: number }, container, text);
    expect(rebuilt?.toString()).toBe(range.toString());
  });

  it("rejects a collapsed (zero-length) range", () => {
    const text = "Hello world";
    const container = buildPageDom(text);
    const node = container.querySelector<HTMLElement>(".page-para")?.firstChild as Text;
    const range = document.createRange();
    range.setStart(node, 3);
    range.setEnd(node, 3);
    expect(domRangeToAnchor(range, container, text)).toBeNull();
  });

  it("returns null when an endpoint is outside the page text", () => {
    const text = "Hello world";
    const container = buildPageDom(text);
    const node = container.querySelector<HTMLElement>(".page-para")?.firstChild as Text;
    const outside = document.createElement("p"); // a bare <p>, not a .page-para
    outside.textContent = "elsewhere";
    document.body.appendChild(outside);
    const range = document.createRange();
    range.setStart(outside.firstChild as Text, 0);
    range.setEnd(node, 4);
    expect(domRangeToAnchor(range, container, text)).toBeNull();
  });
});
