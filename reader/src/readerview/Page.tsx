import { Fragment } from "react";

import type { Page as PageDoc } from "@scriptorium/shared";

import { paintParagraph, type Span } from "../annotations/segments";
import type { BundleReader } from "./BundleReader";
import { paragraphIndexForChar, paragraphStarts, splitParagraphs } from "./pagetext";
import { Plate } from "./Plate";

/** One illustration on a page: its asset id, local image path, and within-page anchor offset. */
export type PagePlate = { plateId: string; relPath: string; anchor: number };

// One logical page = one vertically scrolled unit (DESIGN §13 ADR-0004). Layout, top to bottom:
// optional chapter-title header (only on a chapter's first page), the page's illustration(s), and
// the page text as byte-faithful paragraphs. A page may carry MORE than one illustration (pictures
// per scene, DESIGN §8): the first/base plate renders at the top (anchor 0); extras are woven in
// BETWEEN paragraphs at their anchor — never mid-paragraph, so the byte-faithful `.page-para` DOM is
// untouched.
//
// BYTE-FAITHFUL RENDER (the load-bearing invariant, R2 anchors depend on it): paragraphs are exactly
// `text.split("\n\n")`, one <p> each, with `white-space: pre-line` so a lone verse "\n" inside a
// paragraph is preserved. No trimming, no normalization. Paragraphs carry a `.page-para` class in
// document order so Reader can measure their tops and R2 can map selections to offsets. Plate
// <figure>s are siblings between <p>s, so they never touch a `.page-para` text node.
//
// R2 highlights: each paragraph is painted by `paintParagraph` into runs; a colored run becomes a
// `<span class="hl hl-{color}">`, bare text stays a raw text node. The concatenation of run text still
// equals the paragraph exactly (segments.ts guarantees it), so the byte-faithful invariant holds and a
// `.page-para` with highlights still measures/anchors the same.

export function Page({
  page,
  reader,
  chapterTitle,
  plates,
  onOpenLightbox,
  annotations = [],
  flashId = null,
  onHighlightClick,
}: {
  page: PageDoc;
  reader: BundleReader;
  chapterTitle: string | null;
  /** This page's illustrations, ordered top-to-bottom by anchor (may be empty). */
  plates: PagePlate[];
  onOpenLightbox: (src: string, plateId: string) => void;
  /** Highlight/note spans on this page, in canonical offsets (bookmarks excluded). */
  annotations?: Span[];
  /** Annotation id to flash briefly after a jump, or null. */
  flashId?: string | null;
  onHighlightClick?: (id: string, rect: DOMRect) => void;
}) {
  const paragraphs = splitParagraphs(page.text);
  const starts = paragraphStarts(paragraphs);

  // The page's depicted-moment line (scene ledger's best_visual_beat) captions the base plate. The
  // ledger is opaque provenance in the schema, so read the one field narrowly. Derived from this
  // page's own text only → spoiler-safe. One beat per page → only the base (top) plate is captioned.
  // A private per-plate edit (ADR-0033) can override it: `reader.captionFor` returns the override
  // (including "" → show no caption) or undefined → fall back to the beat.
  const beat = (page.ledger as { best_visual_beat?: string } | undefined)?.best_visual_beat?.trim();
  const captionForPlate = (plateId: string): string | null => {
    const override = reader.captionFor?.(plateId);
    if (override !== undefined) return override.trim() ? override : null;
    return beat ? beat : null;
  };

  // A stable 1-based slot per plate (for a distinguishable alt); a lone plate keeps the legacy alt.
  const slotOf = new Map(plates.map((p, i) => [p.plateId, i + 1]));
  const altFor = (p: PagePlate) =>
    plates.length === 1 ? `Plate for page ${page.seq}` : `Plate ${slotOf.get(p.plateId)} for page ${page.seq}`;
  const renderPlate = (p: PagePlate, cap: string | null = null) => (
    <Plate
      key={p.plateId}
      reader={reader}
      relPath={p.relPath}
      alt={altFor(p)}
      caption={cap}
      onOpen={(src) => onOpenLightbox(src, p.plateId)}
    />
  );

  // Resolve each plate to the paragraph it precedes. Anchor 0 (base image) → the top, above the text.
  const topPlates: PagePlate[] = [];
  const platesBeforePara = new Map<number, PagePlate[]>();
  for (const p of plates) {
    const idx = paragraphIndexForChar(starts, p.anchor);
    if (idx <= 0) {
      topPlates.push(p);
    } else {
      const list = platesBeforePara.get(idx) ?? [];
      list.push(p);
      platesBeforePara.set(idx, list);
    }
  }

  return (
    <article className="page" data-page-seq={page.seq}>
      {chapterTitle && <h2 className="chapter-title">{chapterTitle}</h2>}
      {topPlates.map((p, i) => renderPlate(p, i === 0 ? captionForPlate(p.plateId) : null))}
      <div className="page-text">
        {paragraphs.map((para, i) => {
          const runs = paintParagraph(para, starts[i], annotations);
          // Fast path (and R1b-identical DOM) when nothing is highlighted: a single bare text node.
          const plain = runs.length <= 1 && !runs[0]?.color;
          return (
            <Fragment key={i}>
              {(platesBeforePara.get(i) ?? []).map((p) => renderPlate(p))}
              <p className="page-para" style={{ whiteSpace: "pre-line" }}>
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
            </Fragment>
          );
        })}
      </div>
    </article>
  );
}
