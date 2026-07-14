import { Fragment } from "react";

import type { Page as PageDoc } from "@scriptorium/shared";

import { paintParagraph, type Span } from "../annotations/segments";
import type { BundleReader } from "./BundleReader";
import { paragraphStarts, splitParagraphs } from "./pagetext";
import { Plate } from "./Plate";

// One logical page = one vertically scrolled unit (DESIGN §13 ADR-0004). Layout, top to bottom:
// optional chapter-title header (only on a chapter's first page), optional plate (top, full-width),
// then the page text as byte-faithful paragraphs.
//
// BYTE-FAITHFUL RENDER (the load-bearing invariant, R2 anchors depend on it): paragraphs are exactly
// `text.split("\n\n")`, one <p> each, with `white-space: pre-line` so a lone verse "\n" inside a
// paragraph is preserved. No trimming, no normalization. Paragraphs carry a `.page-para` class in
// document order so Reader can measure their tops and R2 can map selections to offsets.
//
// R2 highlights: each paragraph is painted by `paintParagraph` into runs; a colored run becomes a
// `<span class="hl hl-{color}">`, bare text stays a raw text node. The concatenation of run text still
// equals the paragraph exactly (segments.ts guarantees it), so the byte-faithful invariant holds and a
// `.page-para` with highlights still measures/anchors the same.

export function Page({
  page,
  reader,
  chapterTitle,
  plateRelPath,
  onOpenLightbox,
  annotations = [],
  flashId = null,
  onHighlightClick,
}: {
  page: PageDoc;
  reader: BundleReader;
  chapterTitle: string | null;
  plateRelPath: string | null;
  onOpenLightbox: (src: string) => void;
  /** Highlight/note spans on this page, in canonical offsets (bookmarks excluded). */
  annotations?: Span[];
  /** Annotation id to flash briefly after a jump, or null. */
  flashId?: string | null;
  onHighlightClick?: (id: string, rect: DOMRect) => void;
}) {
  const paragraphs = splitParagraphs(page.text);
  const starts = paragraphStarts(paragraphs);

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
        {paragraphs.map((para, i) => {
          const runs = paintParagraph(para, starts[i], annotations);
          // Fast path (and R1b-identical DOM) when nothing is highlighted: a single bare text node.
          const plain = runs.length <= 1 && !runs[0]?.color;
          return (
            <p key={i} className="page-para" style={{ whiteSpace: "pre-line" }}>
              {plain
                ? para
                : runs.map((run, j) =>
                    run.color ? (
                      <span
                        key={j}
                        className={`hl hl-${run.color}${
                          flashId && run.annotIds.includes(flashId) ? " flash" : ""
                        }`}
                        data-annot-id={run.annotIds[run.annotIds.length - 1]}
                        onClick={(e) =>
                          onHighlightClick?.(
                            run.annotIds[run.annotIds.length - 1],
                            e.currentTarget.getBoundingClientRect(),
                          )
                        }
                      >
                        {run.text}
                      </span>
                    ) : (
                      <Fragment key={j}>{run.text}</Fragment>
                    ),
                  )}
            </p>
          );
        })}
      </div>
    </article>
  );
}
