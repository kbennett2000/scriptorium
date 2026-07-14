import { describe, expect, it } from "vitest";

import { paintParagraph, type Run } from "./segments";

// Overlap painting: correctness of the run boundaries + colors, and the load-bearing byte-faithful
// guarantee that the runs always reconstruct the paragraph exactly (verse "\n" included).

const P = "The quick brown fox jumps."; // "quick" = chars 4..9
const join = (runs: Run[]) => runs.map((r) => r.text).join("");

describe("paintParagraph", () => {
  it("no highlights → one bare run that reconstructs the paragraph", () => {
    const runs = paintParagraph(P, 0, []);
    expect(runs).toHaveLength(1);
    expect(runs[0].color).toBeUndefined();
    expect(runs[0].annotIds).toEqual([]);
    expect(join(runs)).toBe(P);
  });

  it("empty paragraph → no runs", () => {
    expect(paintParagraph("", 0, [{ id: "a", start: 0, end: 3, color: "yellow" }])).toEqual([]);
  });

  it("a mid-paragraph highlight splits into three runs", () => {
    const runs = paintParagraph(P, 0, [{ id: "a", start: 4, end: 9, color: "yellow" }]);
    expect(join(runs)).toBe(P);
    const colored = runs.filter((r) => r.color);
    expect(colored).toHaveLength(1);
    expect(colored[0].text).toBe("quick");
    expect(colored[0].color).toBe("yellow");
    expect(colored[0].annotIds).toEqual(["a"]);
  });

  it("respects paraStart (canonical coordinates)", () => {
    const runs = paintParagraph(P, 100, [{ id: "a", start: 104, end: 109, color: "blue" }]);
    expect(runs.find((r) => r.color)?.text).toBe("quick");
  });

  it("clips a highlight overhanging both edges", () => {
    const runs = paintParagraph(P, 10, [{ id: "a", start: -50, end: 1000, color: "green" }]);
    expect(runs).toHaveLength(1);
    expect(runs[0].color).toBe("green");
    expect(runs[0].text).toBe(P);
  });

  it("ignores a highlight that does not intersect the paragraph", () => {
    const runs = paintParagraph(P, 0, [{ id: "a", start: 100, end: 110, color: "pink" }]);
    expect(runs).toHaveLength(1);
    expect(runs[0].color).toBeUndefined();
  });

  it("overlap: the later highlight wins the contested run (later-on-top)", () => {
    const runs = paintParagraph(P, 0, [
      { id: "A", start: 0, end: 10, color: "yellow" },
      { id: "B", start: 5, end: 15, color: "blue" },
    ]);
    expect(join(runs)).toBe(P);
    const contested = runs.find((r) => r.annotIds.length === 2);
    expect(contested?.color).toBe("blue");
    expect(contested?.annotIds).toEqual(["A", "B"]);
    expect(runs.find((r) => r.text === P.slice(0, 5))?.color).toBe("yellow");
    expect(runs.find((r) => r.text === P.slice(10, 15))?.color).toBe("blue");
  });

  it("nested: the inner (later) highlight wins its span", () => {
    const runs = paintParagraph(P, 0, [
      { id: "outer", start: 0, end: 20, color: "yellow" },
      { id: "inner", start: 5, end: 10, color: "pink" },
    ]);
    expect(join(runs)).toBe(P);
    expect(runs.find((r) => r.text === P.slice(5, 10))?.color).toBe("pink");
    expect(runs.find((r) => r.text === P.slice(0, 5))?.color).toBe("yellow");
  });

  it("adjacent (touching) highlights keep distinct colors, no merge", () => {
    const runs = paintParagraph(P, 0, [
      { id: "A", start: 0, end: 5, color: "yellow" },
      { id: "B", start: 5, end: 10, color: "blue" },
    ]);
    expect(join(runs)).toBe(P);
    expect(runs.find((r) => r.text === P.slice(0, 5))?.color).toBe("yellow");
    expect(runs.find((r) => r.text === P.slice(5, 10))?.color).toBe("blue");
  });

  it("preserves a verse newline inside a highlighted run (byte-faithful)", () => {
    const V = "line one\nline two";
    const runs = paintParagraph(V, 0, [{ id: "a", start: 0, end: V.length, color: "yellow" }]);
    expect(join(runs)).toBe(V);
    expect(runs[0].text).toContain("\n");
  });
});
