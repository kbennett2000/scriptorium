/* eslint-disable */
/**
 * This file was automatically generated from a JSON Schema in shared/schemas.
 * DO NOT EDIT IT BY HAND. Instead, edit the schema and run `node shared/gen-types.mjs`.
 */

/**
 * One household profile's private picture edits for one book (artsets/{user}/{book}/edits/edits.json). Each entry records a plate the reader hand-edited after publish: a replaced image (stored beside this file at the SAME relative paths as the bundle, e.g. images/web/plates/{plate_id}.webp) plus an editable caption. Additive and private per profile — it never touches the shared, immutable published bundle or pages/*.json (extends ADR-0014, the per-user art-set channel).
 */
export interface ArtsetEdits {
  /**
   * Permanent book identifier these edits belong to.
   */
  book_id: string;
  /**
   * Id of the household profile that owns these edits (matches users[].id).
   */
  user_id: string;
  /**
   * The book revision whose frozen plates these edits derived from; lets the reader flag an edit as stale after a later household re-publish (it is not auto-invalidated).
   */
  source_revision: number;
  /**
   * Map of plate_id (4-digit page id, or {page_id}-N for an extra same-page plate) to the edit for that plate.
   */
  plates: {
    [k: string]: {
      /**
       * The reader-edited caption shown under the plate (may be empty to show none). Overrides the page's auto-derived best_visual_beat for this profile only.
       */
      caption: string;
      /**
       * The subject prompt the replacement image was generated from (pre-fills the editor on a re-edit).
       */
      prompt: string;
      /**
       * The seed used, or null if the service randomized it.
       */
      seed?: number | null;
      /**
       * The img2img change amount in (0, 1] used against the previous image, or null for a from-scratch render.
       */
      denoise?: number | null;
      /**
       * ISO-8601 UTC timestamp this edit was committed.
       */
      created: string;
    };
  };
}
