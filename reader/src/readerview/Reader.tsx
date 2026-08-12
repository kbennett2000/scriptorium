import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { Annotations, Cast, Manifest, Page as PageDoc, Positions, Selection, Structure } from "@scriptorium/shared";

import { DEFAULT_SET_ID, SetPicker, useArtsets } from "../artsets";
import { CastPage } from "../cast";
import { SearchPanel } from "../search/SearchPanel";
import {
  AnnotationsPanel,
  DEV_USER_ID,
  NoteSheet,
  SelectionBar,
  createHighlight,
  createNote,
  deleteAnnotation,
  domRangeToAnchor,
  hasBookmark,
  liveAnnotations,
  readAnnotations,
  toggleBookmark,
  updateAnnotation,
  type Anchor,
  type Annotation,
  type HighlightColor,
  type Span,
} from "../annotations";
import { useBackHandler, type Storage } from "../shell";
import { HttpArtsetApi, HttpArtsetClient, setState } from "../shelf";
import { SYNC_EVENT, SyncStatusBadge, type SyncStatus } from "../sync";
import type { BundleReader } from "./BundleReader";
import { Lightbox } from "./Lightbox";
import { SetImageBundleReader } from "./SetImageBundleReader";
import { edgeTapAction } from "./nav";
import { Page, type PagePlate } from "./Page";
import { paragraphIndexForChar, paragraphStarts, splitParagraphs, throttle, topVisibleChar } from "./pagetext";
import { deviceId, readPosition, writePosition } from "./position";

// The reading surface for one Resident (or fixture) book (DESIGN §13 ADR-0004). Loads structure +
// selection + annotations once, then walks pages in reading order as scrolled units. Owns navigation
// (buttons / ←→ keys / swipe / edge taps), the plate lightbox, position persist/restore, and the R2
// annotation UX: select → floating bar, note sheet, bookmark toggle, per-book list + jump/flash, and
// tap-a-highlight recolor/note/delete.
//
// The reading path performs ZERO network I/O — everything comes through the injected BundleReader
// (local bytes / inlined fixtures) and the local annotation store. Position `char` is the top-visible
// paragraph offset; we persist on page-turn, on a throttled scroll, and on unmount.

const PLATE_DIR = "images/web/plates";
const SCROLL_PERSIST_MS = 500;
const FLASH_MS = 1200;
const SWIPE_PX = 60;
const DEFAULT_NOTE_COLOR: HighlightColor = "yellow";

// A note being composed: created from a fresh selection, or editing an existing note's text.
type NoteTarget =
  | { mode: "create"; anchor: Anchor; color: HighlightColor }
  | { mode: "edit"; id: string; initial: string };

export function Reader({
  reader,
  storage,
  bookId,
  user = DEV_USER_ID,
  syncStatus,
  onOpenSettings,
  onExit,
}: {
  reader: BundleReader;
  storage: Storage;
  bookId: string;
  user?: string;
  syncStatus?: SyncStatus;
  onOpenSettings?: () => void;
  onExit: () => void;
}) {
  const [structure, setStructure] = useState<Structure | null>(null);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [cast, setCast] = useState<Cast | null>(null);
  const [annDoc, setAnnDoc] = useState<Annotations | null>(null);
  const [savedPos, setSavedPos] = useState<Positions | null>(null);
  const [chipDismissed, setChipDismissed] = useState(false);
  const [index, setIndex] = useState(0);
  // Furthest page reached this session (1-based seq). Seeds the cast filter live as the reader advances,
  // combined with any synced furthest from `savedPos`. See `furthestSeq` below.
  const [maxSeq, setMaxSeq] = useState(1);
  const [searchOpen, setSearchOpen] = useState(false);
  const [castOpen, setCastOpen] = useState(false);
  const [picsOpen, setPicsOpen] = useState(false);
  const autoCastShown = useRef(false);
  // Which picture set is displayed (DESIGN §8, ADR-0014): Default (shipped art) or one of this
  // profile's private sets. useArtsets owns the list + make/switch/delete; the active choice drives the
  // image source (`effectiveReader`) below. A set changes only how pictures look — never the words,
  // layout, or anchors, so text/JSON always read through the base book `reader`.
  const artsetApi = useMemo(() => new HttpArtsetApi(), []);
  const artsetDownload = useMemo(() => new HttpArtsetClient(), []);
  const artsets = useArtsets(artsetApi, artsetDownload, storage, user, bookId, picsOpen);
  const { activeSetId } = artsets;
  const [effectiveReader, setEffectiveReader] = useState<BundleReader>(reader);
  const [pageDoc, setPageDoc] = useState<PageDoc | null>(null);
  const [lightboxSrc, setLightboxSrc] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // R2 annotation UI state.
  const [pendingSel, setPendingSel] = useState<{
    anchor: Anchor;
    rect: { top: number; bottom: number; left: number; width: number };
    text: string;
  } | null>(null);
  const [noteTarget, setNoteTarget] = useState<NoteTarget | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);
  const [hlMenu, setHlMenu] = useState<{ id: string; rect: DOMRect } | null>(null);
  const [flashId, setFlashId] = useState<string | null>(null);
  const [flashPage, setFlashPage] = useState(false);
  const flashTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const deviceRef = useRef<string>("");
  // Char offset to restore once the page for `index` has rendered (from a saved position); consumed once.
  const pendingRestoreChar = useRef<number | null>(null);

  // Reading order = chapters (by list order) flattened to their page_ids.
  const pageIds = useMemo(
    () => (structure ? structure.chapters.flatMap((c) => c.page_ids) : []),
    [structure],
  );
  const currentId = useMemo(() => pageIds[index] ?? null, [pageIds, index]);
  // A chapter's first page shows that chapter's title header.
  const titleByFirstPage = useMemo(() => {
    const m = new Map<string, string>();
    for (const c of structure?.chapters ?? []) {
      if (c.page_ids.length) m.set(c.page_ids[0], c.title);
    }
    return m;
  }, [structure]);
  // A page's illustrations, grouped by page id, ordered top-to-bottom by anchor. Non-retired only
  // (DESIGN §4.4): retired plates keep their files but must not render. A page's first/base plate
  // uses the bare page_id at anchor 0 (top); evenly-spaced extras use compound ids + a within-page
  // anchor (pictures per scene, DESIGN §8). Built from selection.json — no extra I/O (zero-online).
  const platesByPage = useMemo(() => {
    const m = new Map<string, PagePlate[]>();
    for (const p of selection?.plates ?? []) {
      if (p.status === "retired") continue;
      const plateId = p.plate_id ?? p.page_id;
      const list = m.get(p.page_id) ?? [];
      list.push({ plateId, relPath: `${PLATE_DIR}/${plateId}.webp`, anchor: p.anchor ?? 0 });
      m.set(p.page_id, list);
    }
    for (const list of m.values()) {
      list.sort((a, b) => a.anchor - b.anchor || a.plateId.localeCompare(b.plateId));
    }
    return m;
  }, [selection]);

  // Highlight/note spans on the current page (bookmarks are page-level, not rendered as spans).
  const pageSpans = useMemo<Span[]>(() => {
    if (!annDoc || !currentId) return [];
    return liveAnnotations(annDoc).flatMap((a) =>
      (a.type === "highlight" || a.type === "note") && a.page_id === currentId && a.color
        ? [{ id: a.id, start: a.anchor.start, end: a.anchor.end, color: a.color }]
        : [],
    );
  }, [annDoc, currentId]);
  const bookmarked = useMemo(
    () => (annDoc && currentId ? hasBookmark(annDoc, currentId) : false),
    [annDoc, currentId],
  );

  // Load structure + selection + annotations + device id + saved position once.
  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const [st, sel, castDoc] = await Promise.all([
          reader.readJson<Structure>("structure.json"),
          reader.readJson<Selection>("selection.json"),
          reader.readJson<Cast>("cast.json").catch(() => null),
        ]);
        deviceRef.current = await deviceId(storage);
        const saved = await readPosition(storage, user, bookId);
        const anns = await readAnnotations(storage, bookId, user);
        if (!live) return;
        setStructure(st);
        setSelection(sel);
        setCast(castDoc);
        setAnnDoc(anns);
        setSavedPos(saved);
        if (saved) {
          // page_seq is 1-based book-wide reading order, contiguous — so index = seq - 1 (clamped).
          const order = st.chapters.flatMap((c) => c.page_ids);
          setIndex(Math.min(Math.max(saved.current.page_seq - 1, 0), Math.max(order.length - 1, 0)));
          setMaxSeq(saved.furthest.page_seq);
          pendingRestoreChar.current = saved.current.char;
        } else if (castDoc && castDoc.characters.some((c) => c.major)) {
          // Fresh open (no saved position): show the dramatis-personae interstitial before chapter 1
          // (DESIGN §13), once. The furthest-read filter still applies (only page-1 cast is revealed).
          autoCastShown.current = true;
          setCastOpen(true);
        }
      } catch (e) {
        if (live) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      live = false;
    };
  }, [reader, storage, bookId, user]);

  // After a successful sync, re-read the merged annotations + position so another device's edits (and
  // an advanced `furthest`) appear live without leaving the page. Read-only — never moves the reader.
  useEffect(() => {
    const onSynced = (e: Event) => {
      if ((e as CustomEvent).detail?.book !== bookId) return;
      void (async () => {
        const [anns, pos] = await Promise.all([
          readAnnotations(storage, bookId, user),
          readPosition(storage, user, bookId),
        ]);
        setAnnDoc(anns);
        if (pos) setSavedPos(pos);
      })();
    };
    window.addEventListener(SYNC_EVENT, onSynced);
    return () => window.removeEventListener(SYNC_EVENT, onSynced);
  }, [storage, bookId, user]);

  // Release the reader's object URLs (and any pending flash timer) when the surface unmounts.
  useEffect(() => () => reader.dispose(), [reader]);

  // Point image reads at the active picture set (ADR-0014 Phase 4). Default (or a not-yet-downloaded
  // set) → the base book `reader`; a resident personal set → a SetImageBundleReader that draws images
  // from artsets/{user}/{book}/{setId}/ while delegating all text/JSON to the book. Swapping the reader
  // instance re-resolves every Plate (its effect keys on `reader`). The set reader is disposed when the
  // choice changes or the surface unmounts; the base reader is owned by its own dispose effect above.
  useEffect(() => {
    let live = true;
    let built: SetImageBundleReader | null = null;
    if (activeSetId === DEFAULT_SET_ID) {
      setEffectiveReader(reader);
    } else {
      void (async () => {
        try {
          if ((await setState(storage, user, bookId, activeSetId)) !== "resident") {
            if (live) setEffectiveReader(reader); // not downloaded yet — stay on Default art
            return;
          }
          const root = `artsets/${user}/${bookId}/${activeSetId}`;
          const manifest = JSON.parse(
            await storage.readText(`${root}/manifest.local.json`),
          ) as Manifest;
          if (!live) return;
          built = new SetImageBundleReader(reader, storage, root, manifest);
          setEffectiveReader(built);
        } catch {
          if (live) setEffectiveReader(reader);
        }
      })();
    }
    return () => {
      live = false;
      if (built) built.dispose();
    };
  }, [activeSetId, reader, storage, user, bookId]);
  useEffect(() => () => {
    if (flashTimer.current) clearTimeout(flashTimer.current);
  }, []);

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

  // Track the furthest page reached this session (drives the cast filter live, alongside synced furthest).
  useEffect(() => {
    if (pageDoc) setMaxSeq((m) => Math.max(m, pageDoc.seq));
  }, [pageDoc]);

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
      await writePosition(storage, user, bookId, { page_seq: pageDoc.seq, char }, deviceRef.current);
    },
    [storage, user, bookId, pageDoc],
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
    void persist(
      topVisibleChar(
        paragraphStarts(splitParagraphs(pageDoc.text)),
        paragraphTops(),
        container?.scrollTop ?? 0,
      ),
    );
  }, [pageDoc, paragraphTops, persist]);

  // A live (non-collapsed) text selection blocks page-turns so a selection drag is never a nav gesture.
  const selectionCollapsed = () => document.getSelection()?.isCollapsed ?? true;

  const go = useCallback(
    (delta: number) => {
      if (!selectionCollapsed()) return;
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

  // Touch: a horizontal drag past the threshold is a swipe page-turn; a quick tap in the outer edge
  // is an edge page-turn (edgeTapAction). Both go through `go`, which ignores them mid-selection. The
  // R1b transparent tap-zone <button>s are gone, so text under the page edges stays selectable.
  const touchStart = useRef<{ x: number; y: number; t: number } | null>(null);
  const onTouchStart = (e: React.TouchEvent) => {
    const t = e.changedTouches[0];
    touchStart.current = t ? { x: t.clientX, y: t.clientY, t: Date.now() } : null;
  };
  const onTouchEnd = (e: React.TouchEvent) => {
    const start = touchStart.current;
    touchStart.current = null;
    const t = e.changedTouches[0];
    if (!start || !t) return;
    const dx = t.clientX - start.x;
    const dy = t.clientY - start.y;
    if (Math.abs(dx) > SWIPE_PX && Math.abs(dx) > Math.abs(dy)) {
      go(dx < 0 ? 1 : -1);
      return;
    }
    const width = e.currentTarget.clientWidth || 1;
    const action = edgeTapAction({
      dx,
      dy,
      durationMs: Date.now() - start.t,
      xFraction: t.clientX / width,
      selectionCollapsed: selectionCollapsed(),
    });
    if (action) go(action);
  };

  // Capture a live text selection inside the page text into a pending anchor (drives the floating bar).
  const captureSelection = useCallback(() => {
    const sel = document.getSelection();
    const container = scrollRef.current?.querySelector<HTMLElement>(".page-text");
    if (!sel || sel.rangeCount === 0 || sel.isCollapsed || !container || !pageDoc) {
      setPendingSel(null);
      return;
    }
    const range = sel.getRangeAt(0);
    const anchor = domRangeToAnchor(range, container, pageDoc.text);
    if (!anchor) {
      setPendingSel(null);
      return;
    }
    // Range.getBoundingClientRect exists in browsers but not jsdom; fall back to the origin under test.
    const r =
      typeof range.getBoundingClientRect === "function"
        ? range.getBoundingClientRect()
        : { top: 0, bottom: 0, left: 0, width: 0 };
    setPendingSel({
      anchor,
      rect: { top: r.top, bottom: r.bottom, left: r.left, width: r.width },
      text: range.toString(),
    });
  }, [pageDoc]);

  useEffect(() => {
    // While a modal-ish surface owns the interaction, don't track selection.
    if (lightboxSrc || panelOpen || noteTarget) return;
    const onSel = () => captureSelection();
    document.addEventListener("selectionchange", onSel);
    return () => document.removeEventListener("selectionchange", onSel);
  }, [captureSelection, lightboxSrc, panelOpen, noteTarget]);

  const clearSelection = useCallback(() => {
    document.getSelection()?.removeAllRanges();
    setPendingSel(null);
  }, []);

  const flash = useCallback((annotation: Annotation) => {
    if (flashTimer.current) clearTimeout(flashTimer.current);
    if (annotation.type === "bookmark") {
      setFlashPage(true);
      setFlashId(null);
    } else {
      setFlashId(annotation.id);
      setFlashPage(false);
    }
    flashTimer.current = setTimeout(() => {
      setFlashId(null);
      setFlashPage(false);
    }, FLASH_MS);
  }, []);

  // --- annotation actions (each re-reads the returned doc into state) ---

  const addHighlight = useCallback(
    async (color: HighlightColor) => {
      if (!pendingSel || !currentId) return;
      const doc = await createHighlight(
        storage,
        bookId,
        { page_id: currentId, anchor: pendingSel.anchor, color },
        undefined,
        user,
      );
      setAnnDoc(doc);
      clearSelection();
    },
    [pendingSel, currentId, storage, bookId, user, clearSelection],
  );

  const startNoteFromSelection = useCallback(() => {
    if (!pendingSel) return;
    setNoteTarget({ mode: "create", anchor: pendingSel.anchor, color: DEFAULT_NOTE_COLOR });
    clearSelection();
  }, [pendingSel, clearSelection]);

  const copySelection = useCallback(() => {
    const text = pendingSel?.text ?? "";
    void navigator.clipboard?.writeText(text);
    clearSelection();
  }, [pendingSel, clearSelection]);

  const saveNote = useCallback(
    async (text: string) => {
      if (!noteTarget || !currentId) return;
      const doc =
        noteTarget.mode === "create"
          ? await createNote(
              storage,
              bookId,
              {
                page_id: currentId,
                anchor: noteTarget.anchor,
                color: noteTarget.color,
                text,
              },
              undefined,
              user,
            )
          : await updateAnnotation(storage, bookId, noteTarget.id, { text }, undefined, user);
      setAnnDoc(doc);
      setNoteTarget(null);
    },
    [noteTarget, currentId, storage, bookId, user],
  );

  const onHighlightClick = useCallback((id: string, rect: DOMRect) => {
    // A plain click on a highlight (no active selection) opens its actions; a click that is part of a
    // selection is left to the floating bar.
    if (!(document.getSelection()?.isCollapsed ?? true)) return;
    setHlMenu({ id, rect });
  }, []);

  const recolor = useCallback(
    async (color: HighlightColor) => {
      if (!hlMenu) return;
      const doc = await updateAnnotation(storage, bookId, hlMenu.id, { color }, undefined, user);
      setAnnDoc(doc);
      setHlMenu(null);
    },
    [hlMenu, storage, bookId, user],
  );

  const editNoteFromMenu = useCallback(() => {
    if (!hlMenu || !annDoc) return;
    const target = annDoc.annotations.find((a) => a.id === hlMenu.id);
    setNoteTarget({ mode: "edit", id: hlMenu.id, initial: target?.text ?? "" });
    setHlMenu(null);
  }, [hlMenu, annDoc]);

  const removeAnnotation = useCallback(
    async (id: string) => {
      const doc = await deleteAnnotation(storage, bookId, id, undefined, user);
      setAnnDoc(doc);
      setHlMenu((m) => (m?.id === id ? null : m));
    },
    [storage, bookId, user],
  );

  const onToggleBookmark = useCallback(async () => {
    if (!currentId) return;
    const doc = await toggleBookmark(storage, bookId, currentId, undefined, user);
    setAnnDoc(doc);
  }, [currentId, storage, bookId, user]);

  const jumpTo = useCallback(
    (annotation: Annotation) => {
      const idx = pageIds.indexOf(annotation.page_id);
      if (idx >= 0) setIndex(idx);
      setPanelOpen(false);
      flash(annotation);
    },
    [pageIds, flash],
  );

  // "Jump to furthest read" chip (DESIGN §12/§13): Continue opens `current`; when the household's
  // furthest-read (possibly from another device, after sync) is ahead of it, offer a jump there.
  const furthestAhead =
    savedPos != null &&
    (savedPos.furthest.page_seq > savedPos.current.page_seq ||
      (savedPos.furthest.page_seq === savedPos.current.page_seq &&
        savedPos.furthest.char > savedPos.current.char));

  const jumpToFurthest = useCallback(() => {
    if (!savedPos) return;
    const idx = Math.min(
      Math.max(savedPos.furthest.page_seq - 1, 0),
      Math.max(pageIds.length - 1, 0),
    );
    pendingRestoreChar.current = savedPos.furthest.char;
    setIndex(idx);
    setChipDismissed(true);
  }, [savedPos, pageIds.length]);

  // Furthest-read page seq for the cast filter (ADR-0008): the max of a possibly-synced furthest and
  // the furthest reached this session, so newly-passed characters appear when the cast page reopens.
  const furthestSeq = Math.max(savedPos?.furthest.page_seq ?? 0, maxSeq, 1);

  // Briefly pulse the whole page after a search jump (the match's paragraph is scrolled into view via
  // pendingRestoreChar). Reuses the annotation flash-page mechanism / timer.
  const flashPageOnce = useCallback(() => {
    if (flashTimer.current) clearTimeout(flashTimer.current);
    setFlashId(null);
    setFlashPage(true);
    flashTimer.current = setTimeout(() => setFlashPage(false), FLASH_MS);
  }, []);

  const jumpToSearchHit = useCallback(
    (seq: number, char: number) => {
      const idx = Math.min(Math.max(seq - 1, 0), Math.max(pageIds.length - 1, 0));
      pendingRestoreChar.current = char;
      setIndex(idx);
      setSearchOpen(false);
      flashPageOnce();
    },
    [pageIds.length, flashPageOnce],
  );

  // Android hardware/gesture Back (R5): close the topmost overlay first, then step back a page, then
  // leave to the shelf — never let Back fall through to backgrounding the app while a book is open.
  // No-op on the web (the handler is only ever invoked by the native back button; see shell/native).
  useBackHandler(() => {
    if (lightboxSrc) setLightboxSrc(null);
    else if (noteTarget) setNoteTarget(null);
    else if (hlMenu) setHlMenu(null);
    else if (panelOpen) setPanelOpen(false);
    else if (searchOpen) setSearchOpen(false);
    else if (castOpen) setCastOpen(false);
    else if (pendingSel) clearSelection();
    else if (index > 0) go(-1);
    else onExit();
    return true; // a book is open — Back is always ours (overlay → page → shelf), never app-kill
  });

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

  const chapterTitle = currentId ? (titleByFirstPage.get(currentId) ?? null) : null;
  const currentPlates = currentId ? platesByPage.get(currentId) ?? [] : [];

  return (
    <section className="reader" onTouchStart={onTouchStart} onTouchEnd={onTouchEnd}>
      <div className="reader-bar">
        <button type="button" className="reader-back" onClick={onExit}>
          ← Shelf
        </button>
        <span className="reader-progress">
          {pageIds.length ? `${index + 1} / ${pageIds.length}` : ""}
        </span>
        <div className="reader-bar-actions">
          {syncStatus && <SyncStatusBadge status={syncStatus} />}
          <button
            type="button"
            className="reader-search-btn"
            aria-label="Search"
            onClick={() => setSearchOpen(true)}
          >
            Search
          </button>
          {cast && (
            <button
              type="button"
              className="reader-cast-btn"
              aria-label="Cast"
              onClick={() => setCastOpen(true)}
            >
              Cast
            </button>
          )}
          <button
            type="button"
            className="reader-pics-btn"
            aria-label="Pictures"
            onClick={() => setPicsOpen(true)}
          >
            Pictures
          </button>
          <button
            type="button"
            className={`reader-bookmark${bookmarked ? " on" : ""}`}
            aria-pressed={bookmarked}
            aria-label={bookmarked ? "Remove bookmark" : "Add bookmark"}
            onClick={onToggleBookmark}
          >
            {bookmarked ? "★" : "☆"}
          </button>
          <button
            type="button"
            className="reader-notes-btn"
            aria-label="Annotations"
            onClick={() => setPanelOpen(true)}
          >
            Notes
          </button>
          {onOpenSettings && (
            <button
              type="button"
              className="reader-settings-btn"
              aria-label="Settings"
              onClick={onOpenSettings}
            >
              ⚙
            </button>
          )}
        </div>
      </div>

      {furthestAhead && !chipDismissed && (
        <button type="button" className="jump-furthest-chip" onClick={jumpToFurthest}>
          Jump to furthest read →
        </button>
      )}

      <div
        className={`reader-scroll${flashPage ? " flash-page" : ""}`}
        ref={scrollRef}
        onScroll={() => persistScroll()}
      >
        {pageDoc && (
          <Page
            page={pageDoc}
            reader={effectiveReader}
            chapterTitle={chapterTitle}
            plates={currentPlates}
            onOpenLightbox={setLightboxSrc}
            annotations={pageSpans}
            flashId={flashId}
            onHighlightClick={onHighlightClick}
          />
        )}
      </div>

      <div className="reader-nav">
        <button type="button" onClick={() => go(-1)} disabled={index === 0}>
          Prev
        </button>
        <button type="button" onClick={() => go(1)} disabled={index >= pageIds.length - 1}>
          Next
        </button>
      </div>

      {pendingSel && !noteTarget && (
        <SelectionBar
          rect={pendingSel.rect}
          onColor={addHighlight}
          onNote={startNoteFromSelection}
          onCopy={copySelection}
        />
      )}

      {noteTarget && (
        <NoteSheet
          initial={noteTarget.mode === "edit" ? noteTarget.initial : ""}
          onSave={saveNote}
          onCancel={() => setNoteTarget(null)}
        />
      )}

      {hlMenu && (
        <div
          className="hl-menu"
          role="menu"
          style={{ top: hlMenu.rect.bottom, left: hlMenu.rect.left }}
        >
          {(["yellow", "blue", "green", "pink"] as HighlightColor[]).map((c) => (
            <button
              key={c}
              type="button"
              className={`sel-swatch hl-${c}`}
              aria-label={`Recolor ${c}`}
              onClick={() => recolor(c)}
            />
          ))}
          <button type="button" className="sel-action" onClick={editNoteFromMenu}>
            Note
          </button>
          <button type="button" className="sel-action" onClick={() => removeAnnotation(hlMenu.id)}>
            Delete
          </button>
          <button type="button" className="hl-menu-close" aria-label="Close" onClick={() => setHlMenu(null)}>
            ×
          </button>
        </div>
      )}

      {panelOpen && annDoc && (
        <AnnotationsPanel
          items={liveAnnotations(annDoc)}
          onJump={jumpTo}
          onDelete={removeAnnotation}
          onClose={() => setPanelOpen(false)}
        />
      )}

      {lightboxSrc && (
        <Lightbox src={lightboxSrc} alt="Plate" onClose={() => setLightboxSrc(null)} />
      )}

      {searchOpen && (
        <SearchPanel
          reader={reader}
          storage={storage}
          bookId={bookId}
          pageIds={pageIds}
          onJump={jumpToSearchHit}
          onClose={() => setSearchOpen(false)}
        />
      )}

      {castOpen && cast && (
        <CastPage
          reader={effectiveReader}
          cast={cast}
          furthestSeq={furthestSeq}
          onClose={() => setCastOpen(false)}
        />
      )}

      {picsOpen && (
        <SetPicker
          sets={artsets.sets}
          styles={artsets.styles}
          activeSetId={activeSetId}
          online={artsets.online}
          busy={artsets.busy}
          error={artsets.error}
          onChoose={(id) => void artsets.choose(id)}
          onCreate={(kind, styleId) => void artsets.create(kind, styleId)}
          onDelete={(id) => void artsets.remove(id)}
          onRetry={(id) => void artsets.retry(id)}
          onClose={() => setPicsOpen(false)}
        />
      )}
    </section>
  );
}
