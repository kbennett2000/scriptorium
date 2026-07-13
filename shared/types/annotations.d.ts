/* eslint-disable */
/**
 * This file was automatically generated from a JSON Schema in shared/schemas.
 * DO NOT EDIT IT BY HAND. Instead, edit the schema and run `node shared/gen-types.mjs`.
 */

/**
 * One user's annotations for one book (sync/annotations/{user}/{book}.json). The only mutable layer; merged server-authoritatively by last-writer-wins with tombstones (DESIGN §4.5, §12).
 */
export interface Annotations {
  /**
   * Permanent book identifier these annotations belong to.
   */
  book_id: string;
  /**
   * Id of the household profile that owns these annotations (matches users[].id).
   */
  user_id: string;
  /**
   * All annotations, including tombstones (deleted=true), for last-writer-wins merge.
   */
  annotations: {
    /**
     * Client-generated stable id (UUID) for the annotation; merge key.
     */
    id: string;
    /**
     * Annotation kind: a text highlight, a note (highlight plus body text), or a page-level bookmark.
     */
    type: "highlight" | "note" | "bookmark";
    /**
     * Zero-padded 4-digit page id the annotation anchors to.
     */
    page_id: string;
    /**
     * Character range within the page's immutable text. Offsets are UTF-16 code-unit offsets, because that is what the browser's Selection/Range API yields; the server never interprets them (DESIGN §4.5). A bookmark uses {start:0,end:0} (page-level).
     */
    anchor: {
      /**
       * Inclusive start offset (UTF-16 code units) into the page text.
       */
      start: number;
      /**
       * Exclusive end offset (UTF-16 code units) into the page text; >= start.
       */
      end: number;
    };
    /**
     * Note body. Present only for type='note'.
     */
    text?: string;
    /**
     * Highlight color. Present for highlight/note; absent for bookmark.
     */
    color?: "yellow" | "blue" | "green" | "pink";
    /**
     * ISO-8601 UTC creation timestamp.
     */
    created: string;
    /**
     * ISO-8601 UTC last-modified timestamp; drives last-writer-wins merge (DESIGN §12).
     */
    modified: string;
    /**
     * Tombstone flag. When true the annotation is deleted but retained for merge convergence (DESIGN §12).
     */
    deleted: boolean;
  }[];
}
