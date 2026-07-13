/* eslint-disable */
/**
 * This file was automatically generated from a JSON Schema in shared/schemas.
 * DO NOT EDIT IT BY HAND. Instead, edit the schema and run `node shared/gen-types.mjs`.
 */

/**
 * One user's reading position for one book (sync/positions/{user}/{book}.json). Identity (user, book) lives in the file path, not the document. Merged as furthest-read-wins plus last-writer-wins current (DESIGN §4.5, §12).
 */
export interface Positions {
  /**
   * The furthest point ever reached. Merged by max tuple (page_seq, char) regardless of timestamp (furthest-read-wins).
   */
  furthest: {
    /**
     * 1-based page sequence number of the furthest position.
     */
    page_seq: number;
    /**
     * UTF-16 character offset within that page.
     */
    char: number;
    /**
     * ISO-8601 UTC timestamp this furthest value was recorded.
     */
    modified: string;
  };
  /**
   * The current reading position ('Continue' opens this). Merged by greater 'modified' (last-writer-wins).
   */
  current: {
    /**
     * 1-based page sequence number of the current position.
     */
    page_seq: number;
    /**
     * UTF-16 character offset within that page.
     */
    char: number;
    /**
     * ISO-8601 UTC timestamp this current position was recorded.
     */
    modified: string;
    /**
     * Optional label of the device that recorded this position (e.g. 'pixel8'), for display.
     */
    device?: string;
  };
}
