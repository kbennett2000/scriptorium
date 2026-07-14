import type { Storage } from "../shell";

// Reader display preferences (DESIGN §13): theme (light/sepia/dark), font size (5 steps), typeface
// (Literata/Inter). Persisted PER DEVICE at settings/prefs.json (not synced — display is a device
// concern, unlike annotations/positions). `applyPrefs` writes CSS custom properties + a data-theme
// attribute on the document root; index.css maps those tokens onto the reading surface. All local.

export type Theme = "light" | "sepia" | "dark";
export type Typeface = "literata" | "inter";

export interface Prefs {
  theme: Theme;
  /** 0..4 — index into FONT_SCALES. */
  fontStep: number;
  typeface: Typeface;
}

export const THEMES: Theme[] = ["light", "sepia", "dark"];
export const TYPEFACES: Typeface[] = ["literata", "inter"];
/** Five reading-text scale steps (multipliers on the base rem). Index 2 = 1.0 (default). */
export const FONT_SCALES = [0.85, 0.925, 1, 1.125, 1.25];
export const FONT_STEPS = FONT_SCALES.length;

export const DEFAULT_PREFS: Prefs = { theme: "light", fontStep: 2, typeface: "literata" };

const PREFS_PATH = "settings/prefs.json";

const clampStep = (n: number): number =>
  Number.isFinite(n) ? Math.min(Math.max(Math.round(n), 0), FONT_STEPS - 1) : DEFAULT_PREFS.fontStep;

/** Read persisted prefs, falling back to defaults for a missing file or any unknown/invalid field. */
export async function readPrefs(storage: Storage): Promise<Prefs> {
  try {
    const raw = JSON.parse(await storage.readText(PREFS_PATH)) as Partial<Prefs>;
    return {
      theme: THEMES.includes(raw.theme as Theme) ? (raw.theme as Theme) : DEFAULT_PREFS.theme,
      fontStep: clampStep(raw.fontStep ?? DEFAULT_PREFS.fontStep),
      typeface: TYPEFACES.includes(raw.typeface as Typeface)
        ? (raw.typeface as Typeface)
        : DEFAULT_PREFS.typeface,
    };
  } catch {
    return { ...DEFAULT_PREFS };
  }
}

export async function writePrefs(storage: Storage, prefs: Prefs): Promise<void> {
  await storage.writeText(PREFS_PATH, JSON.stringify(prefs));
}

const FONT_FAMILIES: Record<Typeface, string> = {
  literata: '"Literata Variable", Georgia, "Times New Roman", serif',
  inter: '"Inter Variable", system-ui, sans-serif',
};

/** Apply prefs to the document root as tokens consumed by index.css. No-op outside a DOM. */
export function applyPrefs(prefs: Prefs): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  root.setAttribute("data-theme", prefs.theme);
  root.style.setProperty("--reader-font-scale", String(FONT_SCALES[prefs.fontStep] ?? 1));
  root.style.setProperty("--reader-font", FONT_FAMILIES[prefs.typeface]);
}
