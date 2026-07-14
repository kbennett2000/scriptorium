import { describe, expect, it } from "vitest";

import { MemoryStorage } from "../shell";
import {
  applyPrefs,
  DEFAULT_PREFS,
  FONT_SCALES,
  readPrefs,
  writePrefs,
  type Prefs,
} from "./prefs";

// Reader display prefs: per-device round-trip, defaults for a missing/garbage file, and the DOM
// application (data-theme + CSS custom properties) that index.css tokens key off.

describe("prefs persistence", () => {
  it("round-trips a written prefs object", async () => {
    const s = new MemoryStorage();
    const prefs: Prefs = { theme: "dark", fontStep: 4, typeface: "inter" };
    await writePrefs(s, prefs);
    expect(await readPrefs(s)).toEqual(prefs);
  });

  it("returns defaults when nothing is stored", async () => {
    expect(await readPrefs(new MemoryStorage())).toEqual(DEFAULT_PREFS);
  });

  it("defaults unknown theme/typeface and clamps a numeric out-of-range fontStep", async () => {
    const s = new MemoryStorage();
    await s.writeText("settings/prefs.json", JSON.stringify({ theme: "neon", fontStep: 99, typeface: "x" }));
    // theme/typeface are enums → default; fontStep is numeric → clamped to the top valid step.
    expect(await readPrefs(s)).toEqual({ theme: "light", fontStep: FONT_SCALES.length - 1, typeface: "literata" });
  });

  it("defaults a non-numeric fontStep", async () => {
    const s = new MemoryStorage();
    await s.writeText("settings/prefs.json", JSON.stringify({ theme: "dark", fontStep: "big", typeface: "inter" }));
    expect(await readPrefs(s)).toEqual({ theme: "dark", fontStep: DEFAULT_PREFS.fontStep, typeface: "inter" });
  });
});

describe("applyPrefs", () => {
  it("sets data-theme and the font tokens on the document root", () => {
    applyPrefs({ theme: "sepia", fontStep: 0, typeface: "inter" });
    const root = document.documentElement;
    expect(root.getAttribute("data-theme")).toBe("sepia");
    expect(root.style.getPropertyValue("--reader-font-scale")).toBe(String(FONT_SCALES[0]));
    expect(root.style.getPropertyValue("--reader-font")).toContain("Inter");

    applyPrefs({ theme: "dark", fontStep: 4, typeface: "literata" });
    expect(root.getAttribute("data-theme")).toBe("dark");
    expect(root.style.getPropertyValue("--reader-font-scale")).toBe(String(FONT_SCALES[4]));
    expect(root.style.getPropertyValue("--reader-font")).toContain("Literata");
  });
});
