import { describe, expect, it } from "vitest";

import { edgeTapAction } from "./nav";

// The pure edge-tap decision that replaced R1b's selection-stealing tap-zone buttons.

const base = { dx: 0, dy: 0, durationMs: 100, xFraction: 0.5, selectionCollapsed: true };

describe("edgeTapAction", () => {
  it("a clean tap in the left edge turns back", () => {
    expect(edgeTapAction({ ...base, xFraction: 0.05 })).toBe(-1);
  });

  it("a clean tap in the right edge turns forward", () => {
    expect(edgeTapAction({ ...base, xFraction: 0.95 })).toBe(1);
  });

  it("a tap in the center does nothing", () => {
    expect(edgeTapAction({ ...base, xFraction: 0.5 })).toBe(0);
  });

  it("a drag in an edge is not a tap (left to swipe / selection)", () => {
    expect(edgeTapAction({ ...base, xFraction: 0.05, dx: 40 })).toBe(0);
    expect(edgeTapAction({ ...base, xFraction: 0.95, dy: 40 })).toBe(0);
  });

  it("a long press in an edge is not a tap", () => {
    expect(edgeTapAction({ ...base, xFraction: 0.95, durationMs: 800 })).toBe(0);
  });

  it("never turns while a selection is active — even a clean edge tap", () => {
    expect(edgeTapAction({ ...base, xFraction: 0.05, selectionCollapsed: false })).toBe(0);
    expect(edgeTapAction({ ...base, xFraction: 0.95, selectionCollapsed: false })).toBe(0);
  });

  it("treats exactly 12% / 88% as inside the edge zones", () => {
    expect(edgeTapAction({ ...base, xFraction: 0.12 })).toBe(-1);
    expect(edgeTapAction({ ...base, xFraction: 0.88 })).toBe(1);
  });
});
