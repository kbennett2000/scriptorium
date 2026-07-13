/* eslint-disable */
/**
 * This file was automatically generated from a JSON Schema in shared/schemas.
 * DO NOT EDIT IT BY HAND. Instead, edit the schema and run `node shared/gen-types.mjs`.
 */

/**
 * Bundle manifest (manifest.json): the authoritative file list with hashes and sizes, plus the set of files a reader must download. Drives delta sync by path+sha256 (DESIGN §4.3, §4.4).
 */
export interface Manifest {
  /**
   * Permanent book identifier (see meta.book_id).
   */
  book_id: string;
  /**
   * Bundle revision this manifest describes.
   */
  revision: number;
  /**
   * Bundle format generation (v1 bundles are always 1).
   */
  bundle_version: 1;
  /**
   * Every file in the bundle, with content hash and byte size. The delta-sync unit: clients download new/changed paths by comparing sha256.
   */
  files: {
    /**
     * Bundle-relative POSIX path (e.g. 'pages/0001.json').
     */
    path: string;
    /**
     * Lowercase hex SHA-256 of the file contents.
     */
    sha256: string;
    /**
     * File size in bytes.
     */
    bytes: number;
  }[];
  /**
   * Glob patterns (bundle-relative) selecting the files a reader downloads by default; full-res archival plates are excluded (DESIGN §4.3).
   */
  reader_required: string[];
  /**
   * Total size in bytes of all reader_required files, for download-size display.
   */
  total_bytes_reader: number;
}
