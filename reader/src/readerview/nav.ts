// Edge-tap page-turn decision (pure, so it can be unit-tested without touch events).
//
// R1b used two transparent `.tap-zone` <button>s over the page edges for touch page-turns. They sit
// `position:absolute` at 12% width and, on narrow viewports where the text column reaches the edges,
// they CAPTURE the pointer and steal drag-selection — the R2 blocker (NOTES From R1b). R2 removes the
// buttons entirely and derives the same edge-tap gesture from the touch handler already on `.reader`,
// so the text underneath stays selectable. This function is that gesture's brain.

export const EDGE_FRACTION = 0.12; // left 12% / right 12% are the tap-to-turn zones
const TAP_MOVE_PX = 10; // movement under this (both axes) is a tap, not a drag/swipe
const TAP_MAX_MS = 250; // and it must be quick — a long press is not a page-turn

export interface EdgeTap {
  dx: number;
  dy: number;
  durationMs: number;
  /** Touch end X as a fraction of the surface width, in [0, 1]. */
  xFraction: number;
  /** Whether the current selection is collapsed (no text selected) at touch-end. */
  selectionCollapsed: boolean;
}

/**
 * Returns the page delta for an edge tap: `-1` (prev, left edge), `+1` (next, right edge), or `0` (not
 * an edge tap — a drag, a swipe, a long press, a center tap, or a tap that ended a text selection). A
 * tap that lands on text but selects nothing (collapsed) in an edge zone still turns the page, which is
 * the intended affordance; ending a real selection near an edge does not.
 */
export function edgeTapAction({ dx, dy, durationMs, xFraction, selectionCollapsed }: EdgeTap): -1 | 0 | 1 {
  if (!selectionCollapsed) return 0;
  const isTap = Math.abs(dx) < TAP_MOVE_PX && Math.abs(dy) < TAP_MOVE_PX && durationMs < TAP_MAX_MS;
  if (!isTap) return 0;
  if (xFraction <= EDGE_FRACTION) return -1;
  if (xFraction >= 1 - EDGE_FRACTION) return 1;
  return 0;
}
