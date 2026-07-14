// The byte-faithful text substrate for the reading surface (DESIGN §13, §6). A page's canonical
// `text` is paragraphs joined by "\n\n", byte-stable forever; annotation anchors (R2) are UTF-16
// code-unit offsets into exactly this string. This module is pure and DOM-free so the offset math can
// be unit-tested hard and reused verbatim by R2 — do NOT reimplement paragraph math elsewhere.
//
// Two hard rules, both load-bearing:
//   1. Render is `text.split("\n\n")` → one <p> per paragraph; a lone "\n" inside a paragraph is a
//      verse line-break and must be preserved (the component uses `white-space: pre-line`).
//   2. All offsets are UTF-16 code units (`String.length` / `.slice`). Never iterate by code point
//      (`[...s]`, `Array.from`, `for…of`, `Intl.Segmenter`) on the offset path — that counts astral
//      characters differently and would desync anchors.

/** Split canonical page text into render paragraphs. Verse "\n" is preserved inside each paragraph. */
export function splitParagraphs(text: string): string[] {
  return text.split("\n\n");
}

/**
 * Exact inverse of {@link splitParagraphs}: `joinParagraphs(splitParagraphs(t)) === t` for ALL `t`
 * (empty / leading / trailing / consecutive-empty paragraphs, verse "\n", odd "\n" runs). `split`/
 * `join` on a fixed delimiter is a total inverse; the rendering-lock test asserts it over fixtures.
 */
export function joinParagraphs(paragraphs: string[]): string {
  return paragraphs.join("\n\n");
}

/**
 * UTF-16 start offset of each paragraph within the canonical text.
 * `starts[i] = Σ_{j<i} paragraphs[j].length + 2*i` — the "\n\n" delimiter is 2 code units, and there
 * are `i` of them before paragraph `i`. Guarantees `text.slice(starts[i], starts[i] + p_i.length) === p_i`.
 */
export function paragraphStarts(paragraphs: string[]): number[] {
  const starts = new Array<number>(paragraphs.length);
  let offset = 0;
  for (let i = 0; i < paragraphs.length; i++) {
    starts[i] = offset;
    offset += paragraphs[i].length + 2; // +2 for the "\n\n" join; the overshoot past the last para is never read
  }
  return starts;
}

/**
 * The paragraph a saved `char` offset lands in: the largest index whose start is ≤ `char` (the
 * restore path for positions). Clamps to 0 for a negative/empty input.
 */
export function paragraphIndexForChar(starts: number[], char: number): number {
  let found = 0;
  for (let i = 0; i < starts.length; i++) {
    if (starts[i] <= char) found = i;
    else break;
  }
  return found;
}

/**
 * Map a scroll position to a canonical UTF-16 `char` offset at PARAGRAPH granularity: the start char
 * of the last paragraph whose pixel top is at/above the viewport top. Pure — the React component
 * supplies real measured tops (`el.offsetTop`), so this is unit-tested without layout (in jsdom all
 * tops collapse to 0 and this returns `char 0`, the correct default).
 *
 * `paragraphTops` MUST be ascending and the same length as `starts`.
 */
export function topVisibleChar(starts: number[], paragraphTops: number[], scrollTop: number): number {
  if (starts.length === 0) return 0;
  // The paragraph with the greatest top that is still at/above the scroll position. Ties break to the
  // FIRST such index (strict `>`), so a degenerate all-equal layout — e.g. jsdom's all-zero rects at
  // scrollTop 0 — resolves to char 0 rather than the last paragraph. Real layouts have strictly
  // increasing tops, so this is the same "last paragraph scrolled past the top edge".
  let bestIdx = 0;
  let bestTop = -Infinity;
  for (let i = 0; i < paragraphTops.length; i++) {
    const top = paragraphTops[i];
    if (top <= scrollTop && top > bestTop) {
      bestTop = top;
      bestIdx = i;
    }
  }
  return starts[bestIdx] ?? 0;
}

/**
 * A trailing-edge throttle: at most one call per `ms`, always firing a final call for the last args.
 * Used to persist position on scroll without thrashing storage. `cancel()` drops a pending trailing call.
 */
export function throttle<A extends unknown[]>(
  fn: (...args: A) => void,
  ms: number,
): ((...args: A) => void) & { cancel: () => void } {
  let last = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let pending: A | null = null;

  const invoke = (now: number, args: A) => {
    last = now;
    fn(...args);
  };

  const throttled = (...args: A): void => {
    const now = Date.now();
    const remaining = ms - (now - last);
    pending = args;
    if (remaining <= 0) {
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
      invoke(now, args);
      pending = null;
    } else if (!timer) {
      timer = setTimeout(() => {
        timer = null;
        if (pending) {
          invoke(Date.now(), pending);
          pending = null;
        }
      }, remaining);
    }
  };

  throttled.cancel = () => {
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
    pending = null;
  };

  return throttled;
}
