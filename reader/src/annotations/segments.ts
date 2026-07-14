// Pure highlight painting: turn a paragraph + the highlights that intersect it into contiguous render
// runs (DESIGN §13, BUILD-PLAN R2 "overlapping highlights: later-on-top, simple"). No DOM — the
// component maps each run to a bare text node or a `<span class="hl hl-{color}">`.
//
// BYTE-FAITHFUL (load-bearing): `runs.map(r => r.text).join("") === paraText` for every input, so the
// rendered paragraph still reconstructs the canonical text exactly (verse "\n" included). The anchor
// math in anchors.ts is independent of this segmentation, but both must agree that a run boundary never
// falls inside a surrogate pair — it can't, because boundaries come from integer anchor offsets which
// are themselves UTF-16 code units.

export type HighlightColor = "yellow" | "blue" | "green" | "pink";

/** A highlight/note projected onto one page, in canonical UTF-16 offsets into the page text. */
export interface Span {
  id: string;
  start: number;
  end: number;
  color?: HighlightColor;
}

/** One contiguous stretch of a paragraph's text sharing the same set of covering highlights. */
export interface Run {
  text: string;
  /** Ids of every highlight covering this run (for click-targeting / delete). Empty = bare text. */
  annotIds: string[];
  /** The winning color (last covering highlight in array order), or undefined for bare text. */
  color?: HighlightColor;
}

/**
 * Segment `paraText` (which starts at canonical offset `paraStart`) into runs, painting the highlights
 * that overlap it. `highlights` is in document/creation order; later entries win a contested run
 * (later-on-top). Highlights that don't intersect the paragraph are ignored; a zero/negative-width
 * intersection contributes nothing.
 */
export function paintParagraph(paraText: string, paraStart: number, highlights: Span[]): Run[] {
  const len = paraText.length;

  // Project each highlight into intra-paragraph coords, clipped to [0, len]; keep only real overlaps.
  // `order` is the index in the input array, so ties resolve to the later-declared highlight.
  const local = highlights
    .map((h, order) => ({
      id: h.id,
      color: h.color,
      order,
      s: Math.max(0, h.start - paraStart),
      e: Math.min(len, h.end - paraStart),
    }))
    .filter((h) => h.e > h.s);

  if (local.length === 0) {
    return len === 0 ? [] : [{ text: paraText, annotIds: [], color: undefined }];
  }

  // Boundary points where the covering set can change: paragraph ends + every clipped edge.
  const points = new Set<number>([0, len]);
  for (const h of local) {
    points.add(h.s);
    points.add(h.e);
  }
  const bounds = [...points].sort((a, b) => a - b);

  const runs: Run[] = [];
  for (let i = 0; i < bounds.length - 1; i++) {
    const a = bounds[i];
    const b = bounds[i + 1];
    if (b <= a) continue;
    const covering = local.filter((h) => h.s <= a && h.e >= b);
    const winner = covering.length ? covering.reduce((x, y) => (y.order >= x.order ? y : x)) : null;
    runs.push({
      text: paraText.slice(a, b),
      annotIds: covering.map((h) => h.id),
      color: winner?.color,
    });
  }
  return runs;
}
