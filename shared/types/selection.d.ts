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
     * Filename stem for this plate's prompt and image assets. Absent means the plate uses the bare page_id (the page's first/only illustration). Additional evenly-spaced illustrations on the same page use '{page_id}-2', '{page_id}-3', … (the 'pictures per scene' feature, DESIGN §8). Optional for back-compat with single-image bundles.
     */
    plate_id?: string;
    /**
     * UTF-16 character offset into the page's text where this illustration is woven in (matches the annotation-anchor convention). Absent/0 means top of the page (the first image). Used by the reader to place extra images between paragraphs.
     */
    anchor?: number;
    /**
     * 0-based index of the even text segment this plate illustrates (0 = first). Provenance for the 'pictures per scene' expansion; absent means the single whole-page illustration.
     */
    segment_index?: number;
    /**
     * Why the page was selected (DESIGN §8): a mandatory chapter opener, a scene boundary, a gap fill, a manual override in review, or an extra evenly-spaced illustration on an already-selected page ('segment').
     */
    reason: "chapter_open" | "scene_boundary" | "fill" | "manual" | "segment";
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
