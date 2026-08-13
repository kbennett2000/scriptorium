/* eslint-disable */
/**
 * This file was automatically generated from a JSON Schema in shared/schemas.
 * DO NOT EDIT IT BY HAND. Instead, edit the schema and run `node shared/gen-types.mjs`.
 */

/**
 * One per-user picture set for one book (artsets/{user}/{book}/{set_id}/set.json). A set changes only HOW a book's illustrations look, never WHICH pages are illustrated or where — that layout lives in the book's shared, immutable selection.json and is identical for every set. Sets are private per household profile and additive: they never touch the published bundle (DESIGN §8, ADR-0014). The synthetic 'default' set is the shipped bundle art and has no set.json on disk.
 */
export interface Artset {
  /**
   * Permanent book identifier this set illustrates.
   */
  book_id: string;
  /**
   * Id of the household profile that owns this set (matches users[].id).
   */
  user_id: string;
  /**
   * Set identifier. 'default' is the shipped bundle art; a personal set is 'set-' + 12 hex. Hex-only after 'set-' can never collide with the -rN revision-variant suffix.
   */
  set_id: string;
  /**
   * How the set was made: 'default' (shipped art), 'style' (re-illustrated in a chosen style), or 'reroll' (same style, fresh pictures).
   */
  kind: "default" | "style" | "reroll";
  /**
   * Human-facing name shown in the reader's Pictures menu (e.g. 'Default', 'Watercolour', 'Re-roll 2').
   */
  label: string;
  /**
   * Art style this set was rendered in (matches a styles.json id). Absent for the default set.
   */
  style_id?: string;
  /**
   * Base SDXL model / checkpoint this set was rendered with (a ComfyUI ckpt_name; ADR-0030), or null to have used the imagegen service's configured default. Absent on sets created before ADR-0030.
   */
  model?: string | null;
  /**
   * Free-text look for the 'custom' style_id (e.g. 'photorealistic'; ADR-0031), or null for a catalog style. Absent on sets created before ADR-0031.
   */
  custom_style?: string | null;
  /**
   * The book revision whose frozen selection/prompts this set derived from.
   */
  source_revision?: number;
  /**
   * Lifecycle: 'generating' while the render job runs, 'ready' once all images exist, 'failed' if it errored.
   */
  status: "generating" | "ready" | "failed";
  /**
   * ISO-8601 UTC creation timestamp.
   */
  created: string;
}
