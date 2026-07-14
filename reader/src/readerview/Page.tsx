import type { Page as PageDoc } from "@scriptorium/shared";

import type { BundleReader } from "./BundleReader";
import { splitParagraphs } from "./pagetext";
import { Plate } from "./Plate";

// One logical page = one vertically scrolled unit (DESIGN §13 ADR-0004). Layout, top to bottom:
// optional chapter-title header (only on a chapter's first page), optional plate (top, full-width),
// then the page text as byte-faithful paragraphs.
//
// BYTE-FAITHFUL RENDER (the load-bearing invariant, R2 anchors depend on it): paragraphs are exactly
// `text.split("\n\n")`, one <p> each, with `white-space: pre-line` so a lone verse "\n" inside a
// paragraph is preserved. No trimming, no normalization. Paragraphs carry a `.page-para` class in
// document order so Reader can measure their tops for position tracking.

export function Page({
  page,
  reader,
  chapterTitle,
  plateRelPath,
  onOpenLightbox,
}: {
  page: PageDoc;
  reader: BundleReader;
  chapterTitle: string | null;
  plateRelPath: string | null;
  onOpenLightbox: (src: string) => void;
}) {
  const paragraphs = splitParagraphs(page.text);

  return (
    <article className="page" data-page-seq={page.seq}>
      {chapterTitle && <h2 className="chapter-title">{chapterTitle}</h2>}
      {plateRelPath && (
        <Plate
          reader={reader}
          relPath={plateRelPath}
          alt={`Plate for page ${page.seq}`}
          onOpen={onOpenLightbox}
        />
      )}
      <div className="page-text">
        {paragraphs.map((para, i) => (
          <p key={i} className="page-para" style={{ whiteSpace: "pre-line" }}>
            {para}
          </p>
        ))}
      </div>
    </article>
  );
}
