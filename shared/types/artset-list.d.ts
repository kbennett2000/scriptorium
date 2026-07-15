/* eslint-disable */
/**
 * This file was automatically generated from a JSON Schema in shared/schemas.
 * DO NOT EDIT IT BY HAND. Instead, edit the schema and run `node shared/gen-types.mjs`.
 */

/**
 * The list of one user's picture sets for one book (sync/artsets/{user}/{book}.json), plus which set is active. Always includes the synthetic 'default' set. Syncs like annotations — server-authoritative merge (a later cycle adds tombstones). A set only changes how the book's illustrations look, never the page text/layout.
 */
export interface ArtsetList {
  /**
   * Permanent book identifier these sets illustrate.
   */
  book_id: string;
  /**
   * Id of the household profile that owns these sets (matches users[].id).
   */
  user_id: string;
  /**
   * Which set the reader currently displays. 'default' or a 'set-<hex>' id.
   */
  active_set_id: string;
  /**
   * Summaries of this user's sets for the book, including the synthetic 'default' entry.
   */
  sets: {
    set_id: string;
    kind: "default" | "style" | "reroll";
    label: string;
    style_id?: string;
    source_revision?: number;
    status: "generating" | "ready" | "failed";
    /**
     * ISO-8601 UTC creation timestamp. Absent for the synthetic default set.
     */
    created?: string;
  }[];
}
