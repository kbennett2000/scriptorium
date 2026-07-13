/* eslint-disable */
/**
 * This file was automatically generated from a JSON Schema in shared/schemas.
 * DO NOT EDIT IT BY HAND. Instead, edit the schema and run `node shared/gen-types.mjs`.
 */

/**
 * One logical page of a bundle (pages/NNNN.json). Text is byte-stable and immutable after first publish; anchors depend on it (DESIGN §4.3, §4.4, §6).
 */
export interface Page {
  /**
   * Zero-padded 4-digit page id, equal to the zero-padded sequence number (e.g. '0007').
   */
  id: string;
  /**
   * 1-based page sequence number across the whole book.
   */
  seq: number;
  /**
   * 1-based index of the chapter this page belongs to (matches structure.chapters[].index).
   */
  chapter: number;
  /**
   * Final immutable page text: paragraphs joined by '\n\n', NFC-normalized, '\n' line endings, no trailing whitespace (DESIGN §6.6). Byte-stable forever — annotation anchors are UTF-16 offsets into this string.
   */
  text: string;
  /**
   * Number of words on this page (whitespace-delimited count used by pagination, DESIGN §6).
   */
  word_count: number;
  /**
   * Scene-ledger for this page: the 'scene-update' transform output stored verbatim (DESIGN §4.3, §7.1 P3). Opaque provenance — its internal shape is owned by text-transform-service, so it is not constrained here. Present in published bundles; absent in early (P0) work-phase pages, which carry text only.
   */
  ledger?: {};
}
