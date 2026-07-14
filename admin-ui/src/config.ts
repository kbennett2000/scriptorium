// Build-time feature flags for the admin workbench.

// The Post-render review screen (rendered thumbs + Regen). Gated behind a flag because the render
// path is the S9 demo stub (FakeImagegen placeholders) and per-plate Regen is not wired until S10.
// Default on so the stub render is inspectable; set VITE_POSTRENDER=0 to hide the screen entirely.
export const POSTRENDER_ENABLED = import.meta.env.VITE_POSTRENDER !== "0";
