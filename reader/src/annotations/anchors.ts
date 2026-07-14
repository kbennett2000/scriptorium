// The load-bearing module of R2: pure DOM<->offset mapping for annotation anchors (DESIGN §4.5, §13).
//
// An anchor is `{start, end}`, a pair of UTF-16 code-unit offsets into a page's canonical, immutable
// `text` (CLAUDE.md immutability is exactly why these can stay dumb integers). The offset arithmetic is
// NOT reinvented here — it reuses `readerview/pagetext.ts` verbatim (NOTES From R1b, binding):
// paragraph `i`'s rendered `<p class="page-para">` begins at `paragraphStarts(splitParagraphs(text))[i]`,
// and the `"\n\n"` join contributes exactly 2 code units between paragraphs.
//
// The two directions are exact inverses over the rendered DOM. `domRangeToAnchor(anchorToDomRange(a))`
// reproduces `a`, and `anchorToDomRange(domRangeToAnchor(r))` selects character-identical text — the
// N>=500 round-trip property test pins this. Both survive a SEGMENTED paragraph (one whose single text
// node has been split into highlight `<span>`s + bare text by `segments.ts`), because the DOM<->offset
// walk is over *all* text nodes in document order within the `.page-para`, never a single-node assumption.
//
// UTF-16 discipline: a DOM `Range`'s text-node offset is already a UTF-16 code-unit offset, and
// `String.length`/`.slice` are UTF-16 — so nothing here ever iterates by code point. Astral characters
// (surrogate pairs) count as 2 units consistently and are never bisected.

import { paragraphIndexForChar, paragraphStarts, splitParagraphs } from "../readerview/pagetext";

export interface Anchor {
  start: number;
  end: number;
}

const PARA_SELECTOR = ".page-para";

/** The `.page-para` element containing `node`, or null if `node` is outside every paragraph. */
function paragraphOf(node: Node, container: HTMLElement): HTMLElement | null {
  const el = node.nodeType === Node.ELEMENT_NODE ? (node as HTMLElement) : node.parentElement;
  const para = el?.closest(PARA_SELECTOR) ?? null;
  // Guard against a `.page-para` that belongs to a different page still mounted in the DOM.
  return para && container.contains(para) ? (para as HTMLElement) : null;
}

/** Ordered list of a page's paragraph elements (document order === paragraph index order). */
function paragraphElements(container: HTMLElement): HTMLElement[] {
  return [...container.querySelectorAll<HTMLElement>(PARA_SELECTOR)];
}

/**
 * Flatten a DOM point `(node, offset)` inside `paraEl` to a UTF-16 offset WITHIN that paragraph. A
 * boundary `Range` from the paragraph's start to the point contains exactly the text that precedes it,
 * so its `.toString().length` IS the intra-paragraph code-unit offset. The DOM spec handles both a
 * text-node offset and an element child-index offset uniformly, and it walks all descendant text — so
 * this is correct whether the paragraph is one text node or has been segmented into highlight spans.
 * `Range.toString()` returns raw character data (not whitespace-collapsed), so a verse "\n" counts as 1.
 */
function paraCharOffset(paraEl: HTMLElement, node: Node, offset: number): number {
  const boundary = paraEl.ownerDocument.createRange();
  boundary.setStart(paraEl, 0);
  boundary.setEnd(node, offset);
  return boundary.toString().length;
}

/** Resolve a UTF-16 offset WITHIN `paraEl` to a concrete `(textNode, offset)` DOM point. */
function resolveParaOffset(paraEl: HTMLElement, target: number): { node: Node; offset: number } {
  const walker = paraEl.ownerDocument.createTreeWalker(paraEl, NodeFilter.SHOW_TEXT);
  let sum = 0;
  let last: Text | null = null;
  for (let t = walker.nextNode() as Text | null; t; t = walker.nextNode() as Text | null) {
    last = t;
    const len = t.length;
    if (target <= sum + len) {
      return { node: t, offset: target - sum };
    }
    sum += len;
  }
  // Past the end (or an empty paragraph): clamp to the end of the last text node, else the element itself.
  if (last) return { node: last, offset: last.length };
  return { node: paraEl, offset: 0 };
}

/**
 * Map a live DOM `Range` (a user selection) to a canonical `{start, end}` anchor, or null if the range
 * isn't a usable text selection: an endpoint outside the page's paragraphs (chapter title, plate), a
 * collapsed/zero-length range, or endpoints spanning different pages. Bookmarks are NOT made this way —
 * they use `{start:0, end:0}` directly (see store.toggleBookmark).
 */
export function domRangeToAnchor(
  range: Range,
  container: HTMLElement,
  pageText: string,
): Anchor | null {
  const startPara = paragraphOf(range.startContainer, container);
  const endPara = paragraphOf(range.endContainer, container);
  if (!startPara || !endPara) return null;

  const paras = paragraphElements(container);
  const startIdx = paras.indexOf(startPara);
  const endIdx = paras.indexOf(endPara);
  if (startIdx < 0 || endIdx < 0) return null;

  const starts = paragraphStarts(splitParagraphs(pageText));
  const start = starts[startIdx] + paraCharOffset(startPara, range.startContainer, range.startOffset);
  const end = starts[endIdx] + paraCharOffset(endPara, range.endContainer, range.endOffset);

  if (end <= start) return null; // collapsed or inverted — not a highlightable selection
  return { start, end };
}

/**
 * Map a canonical `{start, end}` anchor back to a live DOM `Range` over `container`'s paragraphs, or
 * null if the container has no paragraphs. Offsets are clamped into their paragraph so a stale anchor
 * never throws (immutability makes this rare, but defensive).
 */
export function anchorToDomRange(
  anchor: Anchor,
  container: HTMLElement,
  pageText: string,
): Range | null {
  const paras = paragraphElements(container);
  if (paras.length === 0) return null;

  const paragraphs = splitParagraphs(pageText);
  const starts = paragraphStarts(paragraphs);

  const startIdx = paragraphIndexForChar(starts, anchor.start);
  const endIdx = paragraphIndexForChar(starts, anchor.end);
  const startPara = paras[Math.min(startIdx, paras.length - 1)];
  const endPara = paras[Math.min(endIdx, paras.length - 1)];

  const startWithin = anchor.start - starts[Math.min(startIdx, starts.length - 1)];
  const endWithin = anchor.end - starts[Math.min(endIdx, starts.length - 1)];

  const startPoint = resolveParaOffset(startPara, startWithin);
  const endPoint = resolveParaOffset(endPara, endWithin);

  const range = container.ownerDocument.createRange();
  range.setStart(startPoint.node, startPoint.offset);
  range.setEnd(endPoint.node, endPoint.offset);
  return range;
}
