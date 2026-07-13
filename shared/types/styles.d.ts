/* eslint-disable */
/**
 * This file was automatically generated from a JSON Schema in shared/schemas.
 * DO NOT EDIT IT BY HAND. Instead, edit the schema and run `node shared/gen-types.mjs`.
 */

/**
 * Illustration style catalog (styles.json). Each style carries the prompt-assembly strings that turn a subject prompt into an imagegen request; style rides in the prompt, not in the model (DESIGN §9, §10).
 */
export interface Styles {
  /**
   * All available styles. The admin picker sorts consistency_friendly first.
   */
  styles: {
    /**
     * Stable style id referenced by meta.style_id.
     */
    id: string;
    /**
     * Human-readable style name for the picker.
     */
    name: string;
    /**
     * Whether character identity stays consistent across plates in this style. Unfriendly styles get a drift warning in the picker (DESIGN §9).
     */
    consistency_friendly: boolean;
    /**
     * String prepended to the subject prompt for plates (leading style cues).
     */
    prefix: string;
    /**
     * String appended to the subject prompt for plates (trailing style cues).
     */
    suffix: string;
    /**
     * Base negative prompt for this style; joined with derived.avoid at render (DESIGN §10).
     */
    negative: string;
    /**
     * String prepended to portrait subject prompts (bust-composition style cues).
     */
    portrait_prefix: string;
    /**
     * Optional imagegen parameter overrides for this style. Null values mean 'use the imagegen default'; v1 leaves both null (DESIGN §9).
     */
    params: {
      /**
       * Override for the number of diffusion steps, or null for the imagegen default.
       */
      steps: number | null;
      /**
       * Override for the CFG guidance scale, or null for the imagegen default.
       */
      cfg: number | null;
    };
  }[];
}
