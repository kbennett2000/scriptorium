import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { Page as PageDoc, Selection, Structure } from "@scriptorium/shared";

import type { Storage } from "../shell";
import type { BundleReader } from "./BundleReader";
import { Lightbox } from "./Lightbox";
import { Page } from "./Page";
import { paragraphIndexForChar, paragraphStarts, splitParagraphs, throttle, topVisibleChar } from "./pagetext";
import { deviceId, readPosition, writePosition } from "./position";

// The reading surface for one Resident (or fixture) book (DESIGN §13 ADR-0004). Loads structure +
// selection once, then walks pages in reading order as scrolled units. Owns navigation
// (buttons / ←→ keys / swipe / edge tap-zones), the plate lightbox, and position persist/restore.
//
// The reading path performs ZERO network I/O — everything comes through the injected BundleReader
// (local Storage bytes or inlined fixtures). Position `char` is the top-visible paragraph offset
// (see pagetext.topVisibleChar); we persist on page-turn, on a throttled scroll, and on unmount.

const PLATE_DIR = "images/web/plates";
const SCROLL_PERSIST_MS = 500;

export function Reader({
  reader,
  storage,
  bookId,
  onExit,
}: {
  reader: BundleReader;
  storage: Storage;
  bookId: string;
  onExit: () => void;
}) {
  const [structure, setStructure] = useState<Structure | null>(null);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [index, setIndex] = useState(0);
  const [pageDoc, setPageDoc] = useState<PageDoc | null>(null);
  const [lightboxSrc, setLightboxSrc] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const deviceRef = useRef<string>("");
  // Char offset to restore once the page for `index` has rendered (from a saved position); consumed once.
  const pendingRestoreChar = useRef<number | null>(null);

  // Reading order = chapters (by list order) flattened to their page_ids.
  const pageIds = useMemo(
    () => (structure ? structure.chapters.flatMap((c) => c.page_ids) : []),
    [structure],
  );
  // A chapter's first page shows that chapter's title header.
  const titleByFirstPage = useMemo(() => {
    const m = new Map<string, string>();
    for (const c of structure?.chapters ?? []) {
      if (c.page_ids.length) m.set(c.page_ids[0], c.title);
    }
    return m;
  }, [structure]);
  // Non-retired plates only (DESIGN §4.4): retired plates keep their files but must not render.
  const platePages = useMemo(() => {
    const s = new Set<string>();
    for (const p of selection?.plates ?? []) {
      if (p.status !== "retired") s.add(p.page_id);
    }
    return s;
  }, [selection]);

  // Load structure + selection + device id + saved position once.
  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const [st, sel] = await Promise.all([
          reader.readJson<Structure>("structure.json"),
          reader.readJson<Selection>("selection.json"),
        ]);
        deviceRef.current = await deviceId(storage);
        const saved = await readPosition(storage, bookId);
        if (!live) return;
        setStructure(st);
        setSelection(sel);
        if (saved) {
          // page_seq is 1-based book-wide reading order, contiguous — so index = seq - 1 (clamped).
          const order = st.chapters.flatMap((c) => c.page_ids);
          setIndex(Math.min(Math.max(saved.current.page_seq - 1, 0), Math.max(order.length - 1, 0)));
          pendingRestoreChar.current = saved.current.char;
        }
      } catch (e) {
        if (live) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      live = false;
    };
  }, [reader, storage, bookId]);

  // Release the reader's object URLs when the surface unmounts.
  useEffect(() => () => reader.dispose(), [reader]);

  // Lazy-load the current page document whenever the index changes.
  useEffect(() => {
    if (!pageIds.length) return;
    const id = pageIds[index];
    let live = true;
    setPageDoc(null);
    void reader
      .readJson<PageDoc>(`pages/${id}.json`)
      .then((doc) => {
        if (live) setPageDoc(doc);
      })
      .catch((e) => {
        if (live) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      live = false;
    };
  }, [reader, pageIds, index]);

  // Measure each rendered paragraph's top relative to the scroll content (nesting-independent).
  const paragraphTops = useCallback((): number[] => {
    const container = scrollRef.current;
    if (!container) return [];
    const base = container.getBoundingClientRect().top - container.scrollTop;
    return [...container.querySelectorAll<HTMLElement>(".page-para")].map(
      (el) => el.getBoundingClientRect().top - base,
    );
  }, []);

  const persist = useCallback(
    async (char: number) => {
      if (!pageDoc) return;
      await writePosition(storage, bookId, { page_seq: pageDoc.seq, char }, deviceRef.current);
    },
    [storage, bookId, pageDoc],
  );

  const persistScroll = useMemo(
    () =>
      throttle(() => {
        if (!pageDoc) return;
        const starts = paragraphStarts(splitParagraphs(pageDoc.text));
        const container = scrollRef.current;
        const char = topVisibleChar(starts, paragraphTops(), container?.scrollTop ?? 0);
        void persist(char);
      }, SCROLL_PERSIST_MS),
    [pageDoc, paragraphTops, persist],
  );
  useEffect(() => () => persistScroll.cancel(), [persistScroll]);

  // After the current page renders, restore a pending scroll offset, else start at the top and record
  // the new current position (page-turn writes page_seq with char 0 unless restoring).
  useEffect(() => {
    if (!pageDoc) return;
    const container = scrollRef.current;
    const restoreChar = pendingRestoreChar.current;
    pendingRestoreChar.current = null;
    if (container) {
      if (restoreChar != null && restoreChar > 0) {
        const starts = paragraphStarts(splitParagraphs(pageDoc.text));
        const pIdx = paragraphIndexForChar(starts, restoreChar);
        container.scrollTop = paragraphTops()[pIdx] ?? 0;
      } else {
        container.scrollTop = 0;
      }
    }
    void persist(topVisibleChar(
      paragraphStarts(splitParagraphs(pageDoc.text)),
      paragraphTops(),
      container?.scrollTop ?? 0,
    ));
  }, [pageDoc, paragraphTops, persist]);

  const go = useCallback(
    (delta: number) => {
      persistScroll.cancel();
      setIndex((i) => Math.min(Math.max(i + delta, 0), Math.max(pageIds.length - 1, 0)));
    },
    [pageIds.length, persistScroll],
  );

  // Keyboard navigation (desktop). Ignored while the lightbox is open (it owns Esc).
  useEffect(() => {
    if (lightboxSrc) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight") go(1);
      else if (e.key === "ArrowLeft") go(-1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, lightboxSrc]);

  // Touch swipe: horizontal drag past a threshold turns the page.
  const touchStartX = useRef<number | null>(null);
  const onTouchStart = (e: React.TouchEvent) => {
    touchStartX.current = e.changedTouches[0]?.clientX ?? null;
  };
  const onTouchEnd = (e: React.TouchEvent) => {
    const start = touchStartX.current;
    touchStartX.current = null;
    if (start == null) return;
    const dx = (e.changedTouches[0]?.clientX ?? start) - start;
    if (Math.abs(dx) > 60) go(dx < 0 ? 1 : -1);
  };

  if (error) {
    return (
      <section className="reader">
        <button type="button" className="reader-back" onClick={onExit}>
          ← Shelf
        </button>
        <p className="shelf-error">Could not open this book: {error}</p>
      </section>
    );
  }

  const currentId = pageIds[index];
  const chapterTitle = currentId ? (titleByFirstPage.get(currentId) ?? null) : null;
  const plateRelPath =
    currentId && platePages.has(currentId) ? `${PLATE_DIR}/${currentId}.webp` : null;

  return (
    <section className="reader" onTouchStart={onTouchStart} onTouchEnd={onTouchEnd}>
      <div className="reader-bar">
        <button type="button" className="reader-back" onClick={onExit}>
          ← Shelf
        </button>
        <span className="reader-progress">
          {pageIds.length ? `${index + 1} / ${pageIds.length}` : ""}
        </span>
      </div>

      <div className="reader-scroll" ref={scrollRef} onScroll={() => persistScroll()}>
        {pageDoc && (
          <Page
            page={pageDoc}
            reader={reader}
            chapterTitle={chapterTitle}
            plateRelPath={plateRelPath}
            onOpenLightbox={setLightboxSrc}
          />
        )}
      </div>

      {/* Edge tap-zones (touch) — narrow strips outside the text column so they don't block future
          text selection (R2). Buttons cover desktop + accessibility. */}
      <button
        type="button"
        className="tap-zone tap-prev"
        aria-label="Previous page"
        disabled={index === 0}
        onClick={() => go(-1)}
      />
      <button
        type="button"
        className="tap-zone tap-next"
        aria-label="Next page"
        disabled={index >= pageIds.length - 1}
        onClick={() => go(1)}
      />
      <div className="reader-nav">
        <button type="button" onClick={() => go(-1)} disabled={index === 0}>
          Prev
        </button>
        <button type="button" onClick={() => go(1)} disabled={index >= pageIds.length - 1}>
          Next
        </button>
      </div>

      {lightboxSrc && (
        <Lightbox src={lightboxSrc} alt="Plate" onClose={() => setLightboxSrc(null)} />
      )}
    </section>
  );
}
