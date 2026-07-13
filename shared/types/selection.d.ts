/* eslint-disable */
/**
 * This file was automatically generated from a JSON Schema in shared/schemas.
 * DO NOT EDIT IT BY HAND. Instead, edit the schema and run `node shared/gen-types.mjs`.
 */

/**
 * Plate selection for a bundle (selection.json): the density preset, its parameters, and the chosen plates with their lifecycle status. Updated additively across revisions (DESIGN §4.3, §8).
 */
export interface Selection {
  /**
   * Density preset that produced this selection (DESIGN §8).
   */
  preset: "lavish" | "classic" | "sparse";
  /**
   * Effective selection parameters (from the preset table, DESIGN §8).
   */
  params: {
    /**
     * Minimum number of pages between kept plates.
     */
    min_gap: number;
    /**
     * Maximum gap before a fill plate is sought within the window.
     */
    max_gap: number;
    /**
     * Minimum visual_salience [0,1] a fill candidate must clear to be selected.
     */
    salience_floor: number;
    /**
     * Whether the first page of each chapter is a mandatory mark.
     */
    chapter_open: boolean;
    /**
     * Whether pages with scene_changed=true are mandatory marks.
     */
    scene_boundary: boolean;
  };
  /**
   * Selected plates in seq order. Only 'selected' plates flow to prompt derivation and render; 'retired' plates keep their files (additive invariant, DESIGN §4.4, §8).
   */
  plates: {
    /**
     * Zero-padded 4-digit page id the plate illustrates. (Cover and portrait pseudo-plates are tracked in prompts/, not here.)
     */
    page_id: string;
    /**
     * Why the page was selected (DESIGN §8): a mandatory chapter opener, a scene boundary, a gap fill, or a manual override in review.
     */
    reason: "chapter_open" | "scene_boundary" | "fill" | "manual";
    /**
     * Visual salience score [0,1] of the page at selection time.
     */
    salience: number;
    /**
     * Lifecycle of the plate: 'selected' (chosen, not yet approved), 'approved' (locked in review), 'rendered' (pixels exist), 'retired' (deselected in a later revision; files retained).
     */
    status: "selected" | "approved" | "rendered" | "retired";
    /**
     * Bundle revision in which this plate was first selected (DESIGN §8 re-selection).
     */
    added_in_revision: number;
  }[];
}
