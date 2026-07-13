/* eslint-disable */
/**
 * This file was automatically generated from a JSON Schema in shared/schemas.
 * DO NOT EDIT IT BY HAND. Instead, edit the schema and run `node shared/gen-types.mjs`.
 */

/**
 * Household profiles (users.json). A top-level array of passwordless profiles used by the reader's profile picker and to namespace per-user annotations/positions (DESIGN §14, ADR-0005).
 */
export type Users = {
  /**
   * Stable profile id, used to namespace sync files ({user}/{book}). Slug-like.
   */
  id: string;
  /**
   * Display name shown in the profile picker.
   */
  name: string;
  /**
   * Avatar/accent color for this profile, as a CSS hex color (e.g. '#e07a5f').
   */
  color: string;
}[];
