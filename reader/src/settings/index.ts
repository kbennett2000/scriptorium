// The settings feature (DESIGN §13): the full display screen (typeface, font size, theme) + the R3
// concerns (profile switcher, manual sync, storage status), plus the per-device prefs controller.

export { Settings } from "./Settings";
export { usePrefs, type PrefsController } from "./usePrefs";
export {
  applyPrefs,
  readPrefs,
  writePrefs,
  DEFAULT_PREFS,
  FONT_SCALES,
  FONT_STEPS,
  THEMES,
  TYPEFACES,
  type Prefs,
  type Theme,
  type Typeface,
} from "./prefs";
