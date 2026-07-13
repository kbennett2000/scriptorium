/* eslint-disable */
/**
 * This file was automatically generated from a JSON Schema in shared/schemas.
 * DO NOT EDIT IT BY HAND. Instead, edit the schema and run `node shared/gen-types.mjs`.
 */

/**
 * Chapter structure of a bundle (structure.json): the ordered list of chapters and the page ids each contains. Frozen after first publish (DESIGN §4.3, §4.4).
 */
export interface Structure {
  /**
   * Chapters in reading order. Chapters never share a page (DESIGN §6).
   */
  chapters: {
    /**
     * 1-based chapter number in reading order.
     */
    index: number;
    /**
     * Chapter title as detected or edited (e.g. 'I', 'CHAPTER 1', or a book title for single-chapter works).
     */
    title: string;
    /**
     * Zero-padded 4-digit page ids belonging to this chapter, in reading order (e.g. ['0001','0002']).
     *
     * @minItems 1
     */
    page_ids: [string, ...string[]];
  }[];
}
