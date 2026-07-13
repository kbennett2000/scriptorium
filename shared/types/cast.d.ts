/* eslint-disable */
/**
 * This file was automatically generated from a JSON Schema in shared/schemas.
 * DO NOT EDIT IT BY HAND. Instead, edit the schema and run `node shared/gen-types.mjs`.
 */

/**
 * Dramatis personae for a bundle (cast.json): the reduced, canonicalized character list produced by the cast pipeline (DESIGN §4.3, §7.2). This is the published contract; work-phase reducer intermediates (e.g. is_person, descriptors) are not part of it.
 */
export interface Cast {
  /**
   * All characters kept in the cast, majors and minors.
   */
  characters: {
    /**
     * Kebab-case, de-articled, uniquified identifier for this character (DESIGN §7.2). Stable within the bundle; used in portrait filenames and pseudo-plate ids.
     */
    slug: string;
    /**
     * Display name: the most frequent full label for this character (DESIGN §7.2).
     */
    name: string;
    /**
     * Other labels for this character besides the canonical name.
     */
    aliases: string[];
    /**
     * Zero-padded 4-digit page ids on which this character is mentioned, used for the reader's furthest-read cast filter (DESIGN §13, ADR-0008).
     */
    mention_pages: string[];
    /**
     * Whether this character is a major (rendered with a canonical visual description and eligible for a portrait). See the major rule in DESIGN §7.2.
     */
    major: boolean;
    /**
     * Canonical visual description used in prompts and portraits. Null for minors, which get no detailed canonicalization (DESIGN §7.2).
     */
    visual_description: string | null;
    /**
     * One-line character summary for the dramatis-personae page and prompt context.
     */
    one_line: string;
    /**
     * Free-form descriptive tags for the character.
     */
    tags: string[];
    /**
     * Relative bundle path to this character's rendered portrait PNG (e.g. 'images/portraits/time-traveller.png'), or null if no portrait exists.
     */
    portrait: string | null;
    /**
     * True if a human edited this character's visual_description/one_line in the review gate (DESIGN §11.1).
     */
    edited_by_human: boolean;
  }[];
}
