/* eslint-disable */
/**
 * This file was automatically generated from a JSON Schema in shared/schemas.
 * DO NOT EDIT IT BY HAND. Instead, edit the schema and run `node shared/gen-types.mjs`.
 */

/**
 * The prompt record for one plate (prompts/NNNN.json, or the cover/portrait pseudo-plates). Holds the derived illustration prompt, any human edit, and the fully-assembled strings plus render provenance (DESIGN §4.3, §10).
 */
export interface Prompt {
  /**
   * Plate id (also the filename stem): a zero-padded 4-digit page id, an extra evenly-spaced same-page illustration '{page_id}-N' (DESIGN §8 'pictures per scene'), or a pseudo-plate id 'cover' or 'portrait-{slug}' (DESIGN §10).
   */
  page_id: string;
  /**
   * The 'illustration-prompt' transform output stored verbatim (DESIGN §4.3). Opaque — its internal shape (including fields like 'prompt' and 'avoid') is owned by text-transform-service, so it is not constrained here.
   */
  derived: {};
  /**
   * Human-edited subject prompt from the review gate, or null if unedited (DESIGN §11.1).
   */
  edited_prompt: string | null;
  /**
   * The subject prompt actually used: edited_prompt if set, else derived.prompt (DESIGN §4.3).
   */
  final_subject_prompt: string;
  /**
   * The full style-wrapped string sent to imagegen: style.prefix + final_subject_prompt + style.suffix (DESIGN §10). Present after render; absent for draft prompts.
   */
  wrapped_prompt?: string;
  /**
   * The negative prompt sent to imagegen: style.negative joined with derived.avoid (DESIGN §10). Present after render; absent for draft prompts.
   */
  negative_prompt?: string;
  /**
   * Render provenance for this plate. Absent until the plate has been rendered (P7).
   */
  render?: {
    /**
     * ISO-8601 UTC timestamp of the (latest) render.
     */
    at: string;
    /**
     * The render parameters echoed back by the imagegen service (seed, size, steps, etc.). Opaque — shape owned by the imagegen service, not constrained here.
     */
    params_echo?: {};
    /**
     * Number of render attempts made for this plate.
     */
    attempts: number;
  };
}
