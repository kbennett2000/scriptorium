/* eslint-disable */
/**
 * This file was automatically generated from a JSON Schema in shared/schemas.
 * DO NOT EDIT IT BY HAND. Instead, edit the schema and run `node shared/gen-types.mjs`.
 */

/**
 * One household profile's private picture edits for one book (artsets/{user}/{book}/edits/edits.json). Each entry records a plate the reader hand-edited after publish: a replaced image plus an editable caption. Edits are SCOPED to the reader they were made from (ADR-0035): plates[plate_id] maps a scope ('default' for the base book, or a 'set-…' id for a style set) to the edit made while viewing that reader, and the replacement image is stored beside this file under a scope segment (images/web/plates/{scope}/{plate_id}.webp). So switching sets shows that set's own picture unless it too has been edited. Additive and private per profile — it never touches the shared, immutable published bundle or pages/*.json (extends ADR-0014, the per-user art-set channel).
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
   * Map of plate_id (4-digit page id, or {page_id}-N for an extra same-page plate) to that plate's edits, one per scope. The inner map keys a scope ('default' for the base book, or a 'set-…' style-set id) to the edit made while viewing that reader (ADR-0035), so an edit only overrides the set it was made on.
   */
  plates: {
    /**
     * The edits for one plate, keyed by the scope ('default' or a 'set-…' id) they were made under.
     */
    [k: string]: {
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
         * The negative prompt used for the replacement render (empty ⇒ the style's default negative was used).
         */
        negative?: string;
        /**
         * The illustration style the replacement was rendered under (a styles-catalog id, or 'custom' for a free-text look). Defaults to the style of the reader the edit was made from, so a comic-set page re-renders as comic.
         */
        style_id?: string;
        /**
         * Free-text look when style_id is 'custom' (ADR-0031); null/absent for a catalog style.
         */
        custom_style?: string | null;
        /**
         * The base checkpoint (ComfyUI ckpt_name) the replacement was rendered with, or null for the imagegen service's configured default.
         */
        model?: string | null;
        /**
         * The imagegen quality tier ('fast' | 'standard' | 'high') used, or null for the service default.
         */
        quality?: string | null;
        /**
         * IP-Adapter likeness strength applied to the character reference photo, or null when no reference was used or the service default was accepted.
         */
        reference_strength?: number | null;
        /**
         * The reader (scope) this edit was made from: 'default' for the base book, or a 'set-…' style-set id. Redundant with the plate's scope key, recorded so an entry is self-describing.
         */
        set_id?: string;
        /**
         * ISO-8601 UTC timestamp this edit was committed.
         */
        created: string;
        /**
         * An accepted short video (WAN 2.2, ADR-0037) that animates this plate's current picture, stored beside this file at images/video/plates/{scope}/{plate_id}.mp4. The presence of this object is what makes the reader show a play icon on the plate; the reader derives the mp4 path from the scope + plate_id. Absent ⇒ no clip for this plate/scope. Additive and per (scope, plate_id), like the image edit itself.
         */
        video?: {
          /**
           * The motion prompt ('how it should move') the clip was rendered from; pre-fills the editor on a re-render.
           */
          motion_prompt: string;
          /**
           * The animate model wire id used ('wan-5b' | 'remix-14b'), or null for the service's default.
           */
          model?: string | null;
          /**
           * Frame count rendered, or null for the service default.
           */
          frames?: number | null;
          /**
           * Frames per second rendered, or null for the service default.
           */
          fps?: number | null;
          /**
           * The seed used, or null if the service randomized it.
           */
          seed?: number | null;
          /**
           * ISO-8601 UTC timestamp this video was accepted.
           */
          created: string;
        };
      };
    };
  };
}
