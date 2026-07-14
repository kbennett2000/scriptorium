import type { Cast } from "@scriptorium/shared";

// The dramatis-personae spoiler filter (DESIGN §13, ADR-0008 causality). A character is visible only
// once the reader has actually reached a page on which it is mentioned — the same no-spoilers invariant
// the generation pipeline obeys, applied to the reader. `mention_pages` are zero-padded 4-digit page-id
// strings; the reader's furthest-read is a 1-based numeric `page_seq`. Page ids are contiguous with seq
// in a bundle, so the comparison is `parseInt(pageId, 10) <= furthestSeq`.

export type Character = Cast["characters"][number];

/** Characters mentioned on any page at or before the furthest-read page (ADR-0008). Order preserved. */
export function visibleCharacters(cast: Cast, furthestSeq: number): Character[] {
  return cast.characters.filter((c) =>
    c.mention_pages.some((pid) => Number.parseInt(pid, 10) <= furthestSeq),
  );
}
