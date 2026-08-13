/* eslint-disable */
/**
 * This file was automatically generated from a JSON Schema in shared/schemas.
 * DO NOT EDIT IT BY HAND. Instead, edit the schema and run `node shared/gen-types.mjs`.
 */

/**
 * Bundle-level metadata (meta.json). Identity, bake configuration, provenance and summary statistics for one published book. See DESIGN §4.3.
 */
export interface Meta {
  /**
   * Schema/version generation of this bundle. v1 bundles are always 1; the field exists so future bundle formats can be distinguished and migrated (DESIGN §4).
   */
  bundle_version: 1;
  /**
   * Permanent book identifier. Gutenberg books are 'pg-{gutenberg_id}'; user-supplied books are 'usr-{first 12 hex of sha256 of normalized source text}' (DESIGN §4.1). Ids never change and are never reused.
   */
  book_id: string;
  /**
   * Monotonic revision counter, starting at 1 on first publish. Bumped whenever an additive revision (re-selection or plate re-render) changes the bundle (DESIGN §4.4).
   */
  revision: number;
  /**
   * Human-readable book title. From the source adapter, overridable in bake config.
   */
  title: string;
  /**
   * Author name as a display string. May be empty for anonymous/unknown works but the field is always present.
   */
  author: string;
  /**
   * Primary language of the text as a short code (e.g. 'en'). Advisory; feeds transforms and reader typography.
   */
  language: string;
  /**
   * Where the text came from, for provenance and offline re-bake.
   */
  source: {
    /**
     * Origin class of the bundle text. 'gutenberg' = fetched from Project Gutenberg via Gutendex; 'user' = uploaded/pasted/markdown sideload (DESIGN §5.3). Distinct from the admin API request 'kind' (gutenberg|text|markdown), which is not stored here.
     */
    kind: "gutenberg" | "user";
    /**
     * Project Gutenberg book number. Present only when kind = 'gutenberg'.
     */
    gutenberg_id?: number;
    /**
     * ISO-8601 UTC timestamp at which the source text was retrieved/ingested.
     */
    retrieved_at: string;
  };
  /**
   * Historical/aesthetic era for the book (e.g. '1890s England'). Set in bake config (human), defaulted from an admin-UI guess. Feeds the transform prompts (DESIGN §4.3).
   */
  era: string;
  /**
   * Id of the illustration style used for this bake, referencing an entry in styles.json (DESIGN §9), or the sentinel 'custom' for a free-text look (ADR-0031). Not enum-locked because styles are data, not schema.
   */
  style_id: string;
  /**
   * The owner's free-text look for the 'custom' style (e.g. 'photorealistic'; ADR-0031), or null for a catalog style. Pinned so re-renders and art-set re-rolls reproduce it. Absent on bundles published before ADR-0031.
   */
  custom_style?: string | null;
  /**
   * Plate-density preset used for selection (DESIGN §8). One of the three v1 presets.
   */
  density_preset: "lavish" | "classic" | "sparse";
  /**
   * Illustration-richness dial (DESIGN §8). Tightens the selection engine's page spacing so a higher value selects proportionally more distinct pages, one picture each, spread evenly across the whole book. 1 = the preset's default spacing (byte-identical to a single-picture bake). Optional/absent means 1. (Prior meaning: N clustered pictures per scene page — retired in ADR-0016.)
   */
  images_per_scene?: number;
  /**
   * Whether dramatis-personae portraits were rendered for major characters in this bake (DESIGN §10).
   */
  portraits_enabled: boolean;
  /**
   * Provenance of the bake that produced this bundle: when, against which services/models, at which pipeline version. Pins everything needed to reproduce or audit generation (DESIGN §4.3, ADR-0003).
   */
  bake: {
    /**
     * ISO-8601 UTC timestamp at which the bake (publish) completed.
     */
    completed_at: string;
    /**
     * The text-transform-service instance and transform versions used.
     */
    transform_service: {
      /**
       * Host (and optionally port) of the text-transform-service that served this bake.
       */
      url_host: string;
      /**
       * Map of transform name (e.g. 'scene-update', 'cast-mentions') to the exact version string reported by the service at bake time. Keys are transform names; values are version strings.
       */
      transforms: {
        /**
         * Version string of one transform, as reported by the service.
         */
        [k: string]: string;
      };
    };
    /**
     * Model identifiers as reported by the GPU services at bake time.
     */
    models: {
      /**
       * LLM model tag used for text transforms (e.g. 'qwen3:8b'), as reported by the transform service.
       */
      llm: string;
      /**
       * Image-generation model tag used for rendering (e.g. an SDXL variant), as reported by the imagegen service.
       */
      imagegen: string;
    };
    /**
     * Version of the scriptorium pipeline that produced this bundle (e.g. a 'git describe' string).
     */
    pipeline_version: string;
  };
  /**
   * Summary counts for the published bundle, for display and sanity checks.
   */
  stats: {
    /**
     * Total number of logical pages in the bundle.
     */
    pages: number;
    /**
     * Total word count across all pages.
     */
    words: number;
    /**
     * Number of rendered plates (illustrations) in the bundle, excluding cover and portraits.
     */
    plates: number;
    /**
     * Number of chapters detected/used in the bundle.
     */
    chapters: number;
  };
}
