"""The paginator (DESIGN §6): ``RawBook`` → deterministic, byte-stable pages.

This is a **faithful transcription of DESIGN §6 steps 1–7**. The output is
byte-exact and deterministic forever: annotation anchors (R2) are UTF-16 offsets
into each page's immutable ``text``, so a byte that shifts silently corrupts every
downstream annotation. Two properties are load-bearing and locked by tests:

* **Determinism** — same ``RawBook`` + params ⇒ byte-identical pages (§6, last line).
* **Round-trip** — the pages of a chapter reassemble into that chapter's normalized
  text byte-for-byte. To make this hold even when a paragraph is sentence-split
  across a page boundary (where the split whitespace is deliberately dropped so
  pages carry no trailing whitespace), each page-boundary records the exact
  separator that was consumed — the *separator ledger* (:class:`ChapterLayout`).

Normalization (§6.6) is *inherited*, not re-applied: ``ingest.normalize_source_text``
already made the source NFC with ``\\n`` endings before ``RawBook`` existed, and
``split_paragraphs`` already stripped per-line trailing whitespace. The paginator
only ever concatenates those already-canonical strings with ``\\n\\n`` and asserts
the invariant on its own output (see :func:`_check_bytestable`) — one normalization
story, no double-normalizing.
"""

from __future__ import annotations

import re
import unicodedata
from collections import deque
from dataclasses import dataclass

from ..ingest.base import RawBook
from ..schemas import validate as _schema_validate

# Fixed v1 pagination parameters (DESIGN §6).
_TARGET = 550
_MIN = 400
_MAX = 850

# A verse (or otherwise unsplittable) paragraph may push a page up to this multiple
# of ``max`` before it is split on internal line boundaries (DESIGN §6.5).
VERSE_CAP = 1.25

# Sentence boundary: whitespace following sentence-final punctuation (DESIGN §6.3).
_SENTENCE = re.compile(r"(?<=[.!?…])\s+")


@dataclass(frozen=True)
class PaginationParams:
    """Word-count targets for pagination (fixed at v1 defaults, DESIGN §6)."""

    target: int = _TARGET
    min: int = _MIN
    max: int = _MAX

    @property
    def verse_cap_words(self) -> int:
        """Absolute word ceiling for an unsplittable paragraph on a page."""
        return int(self.max * VERSE_CAP)


DEFAULT_PARAMS = PaginationParams()


@dataclass(frozen=True)
class _Unit:
    """A pagination unit: a whole paragraph or a fragment of a split one.

    ``sep_before`` is the exact separator that preceded this unit in the chapter's
    canonical text — ``"\\n\\n"`` before a fresh paragraph, or the whitespace a
    sentence/line split consumed before a fragment. It is what a page boundary
    records so round-trip stays byte-exact across splits.
    """

    text: str
    sep_before: str
    words: int


@dataclass(frozen=True)
class ChapterLayout:
    """Where one chapter's pages live and how to reassemble them byte-exactly."""

    index: int  # 1-based
    title: str
    page_seqs: list[int]
    boundary_seps: list[str]  # length == len(page_seqs) - 1
    canonical_text: str  # "\n\n".join(chapter.paragraphs)


@dataclass
class PaginatedBook:
    """Paginator output: schema-shaped pages, structure.json, and the ledger."""

    pages: list[dict]
    structure: dict
    chapters: list[ChapterLayout]

    def reconstruct_chapter(self, index: int) -> str:
        """Reassemble chapter ``index`` (0-based) from its page texts + ledger.

        Equals ``"\\n\\n".join(chapter.paragraphs)`` byte-for-byte — the round-trip
        guarantee, including across sentence/line splits.
        """
        layout = self.chapters[index]
        text_by_seq = {p["seq"]: p["text"] for p in self.pages}
        parts: list[str] = []
        for k, seq in enumerate(layout.page_seqs):
            if k:
                parts.append(layout.boundary_seps[k - 1])
            parts.append(text_by_seq[seq])
        return "".join(parts)


# --- word counting & invariants --------------------------------------------

def _word_count(text: str) -> int:
    """Whitespace-delimited word count (DESIGN §6)."""
    return len(text.split())


def _mk_unit(text: str, sep_before: str) -> _Unit:
    return _Unit(text=text, sep_before=sep_before, words=_word_count(text))


def _check_bytestable(text: str) -> None:
    """Assert §6.6 holds for a produced page (proves composition without redoing it)."""
    if "\r" in text:
        raise ValueError("page text contains a carriage return")
    if text != unicodedata.normalize("NFC", text):
        raise ValueError("page text is not NFC-normalized")
    if text != text.rstrip():
        raise ValueError("page text has trailing whitespace")


# --- splitting --------------------------------------------------------------

def _split_sentence(
    unit: _Unit, page_words: int, params: PaginationParams
) -> tuple[_Unit, _Unit] | None:
    """Split a prose paragraph at the sentence boundary nearest ``target``.

    Returns ``(head, tail)`` where ``head`` joins the current page and ``tail`` is
    requeued, or ``None`` if the paragraph has no interior sentence boundary. The
    boundary preferring ``page_words + head`` closest to ``target`` while staying
    ``<= max`` is chosen (DESIGN §6.3); ``tail.sep_before`` is the consumed whitespace.
    """
    matches = list(_SENTENCE.finditer(unit.text))
    if not matches:
        return None
    best = None
    best_key: tuple[bool, int] | None = None
    for m in matches:
        head_words = _word_count(unit.text[: m.start()])
        resulting = page_words + head_words
        key = (resulting > params.max, abs(resulting - params.target))
        if best_key is None or key < best_key:
            best_key, best = key, m
    assert best is not None
    head = _mk_unit(unit.text[: best.start()], unit.sep_before)
    tail = _mk_unit(unit.text[best.end() :], unit.text[best.start() : best.end()])
    if head.words == 0:
        return None
    return head, tail


def _split_lines(
    unit: _Unit, page_words: int, params: PaginationParams
) -> tuple[_Unit, _Unit] | None:
    """Split an unsplittable (verse) paragraph on internal line boundaries (§6.5).

    Groups whole lines so ``page_words + head`` is nearest ``target`` without
    exceeding the verse cap; ``tail.sep_before`` is the ``"\\n"`` consumed at the split.
    """
    lines = unit.text.split("\n")
    if len(lines) < 2:
        return None
    best_i = None
    best_key: tuple[bool, int] | None = None
    for i in range(1, len(lines)):
        head_words = _word_count("\n".join(lines[:i]))
        resulting = page_words + head_words
        key = (resulting > params.verse_cap_words, abs(resulting - params.target))
        if best_key is None or key < best_key:
            best_key, best_i = key, i
    assert best_i is not None
    head = _mk_unit("\n".join(lines[:best_i]), unit.sep_before)
    tail = _mk_unit("\n".join(lines[best_i:]), "\n")
    if head.words == 0:
        return None
    return head, tail


# --- per-chapter pagination -------------------------------------------------

def _paginate_chapter(
    units: list[_Unit], params: PaginationParams
) -> list[list[_Unit]]:
    """Greedily pack a chapter's units into pages (DESIGN §6 steps 2–5)."""
    queue: deque[_Unit] = deque(units)
    pages: list[list[_Unit]] = []
    cur: list[_Unit] = []
    cur_words = 0

    def flush() -> None:
        nonlocal cur, cur_words
        if cur:
            pages.append(cur)
            cur = []
            cur_words = 0

    while queue:
        u = queue.popleft()
        splittable = "\n" not in u.text
        ceiling = params.max if splittable else params.verse_cap_words

        if not cur:
            # Fresh page: place ``u``, splitting only if it alone exceeds its ceiling.
            if u.words > ceiling:
                res = (
                    _split_sentence(u, 0, params)
                    if splittable
                    else _split_lines(u, 0, params)
                )
                if res is None:  # unsplittable in practice — place whole (unavoidable)
                    cur.append(u)
                    cur_words += u.words
                    flush()
                    continue
                head, tail = res
                cur.append(head)
                cur_words += head.words
                queue.appendleft(tail)
                flush()
                continue
            cur.append(u)
            cur_words += u.words
            if cur_words >= params.target:
                flush()
            continue

        # Non-empty page.
        if cur_words >= params.target:  # already full enough (§6.2) — start a new page
            queue.appendleft(u)
            flush()
            continue
        if cur_words + u.words <= ceiling:  # fits (verse may ride up to the cap)
            cur.append(u)
            cur_words += u.words
            if cur_words >= params.target:
                flush()
            continue

        # ``u`` would overflow the page and the page is still under target.
        if cur_words < params.min:
            # Closing here leaves the page < min and ``u`` would exceed max → split (§6.3/§6.5).
            res = (
                _split_sentence(u, cur_words, params)
                if splittable
                else _split_lines(u, cur_words, params)
            )
            if res is not None:
                head, tail = res
                cur.append(head)
                cur_words += head.words
                queue.appendleft(tail)
                flush()
                continue
        # Page already >= min, or the unit cannot be split: close it; ``u`` leads the next.
        queue.appendleft(u)
        flush()

    flush()
    return pages


# --- public entry point -----------------------------------------------------

def paginate(
    raw_book: RawBook, params: PaginationParams = DEFAULT_PARAMS
) -> PaginatedBook:
    """Paginate ``raw_book`` into byte-stable pages + ``structure.json`` (DESIGN §6).

    Every page is validated against the ``page`` schema and the structure against
    ``structure`` before return. Deterministic: same input ⇒ byte-identical output.
    """
    pages: list[dict] = []
    structure_chapters: list[dict] = []
    layouts: list[ChapterLayout] = []
    seq = 0

    for c_index, chapter in enumerate(raw_book.chapters, start=1):
        units = [
            _mk_unit(para, "" if j == 0 else "\n\n")
            for j, para in enumerate(chapter.paragraphs)
        ]
        chapter_pages = _paginate_chapter(units, params)
        if not chapter_pages:  # empty chapter still owns exactly one (empty) page
            chapter_pages = [[]]

        title = chapter.title or raw_book.title or str(c_index)
        page_ids: list[str] = []
        page_seqs: list[int] = []
        boundary_seps: list[str] = []

        for n, page_units in enumerate(chapter_pages):
            seq += 1
            text = "\n\n".join(u.text for u in page_units)
            _check_bytestable(text)
            page = {
                "id": f"{seq:04d}",
                "seq": seq,
                "chapter": c_index,
                "text": text,
                "word_count": _word_count(text),
            }
            _schema_validate("page", page)
            pages.append(page)
            page_ids.append(page["id"])
            page_seqs.append(seq)
            if n:  # separator consumed at the boundary before this page
                boundary_seps.append(page_units[0].sep_before if page_units else "\n\n")

        structure_chapters.append(
            {"index": c_index, "title": title, "page_ids": page_ids}
        )
        layouts.append(
            ChapterLayout(
                index=c_index,
                title=title,
                page_seqs=page_seqs,
                boundary_seps=boundary_seps,
                canonical_text="\n\n".join(chapter.paragraphs),
            )
        )

    structure = {"chapters": structure_chapters}
    _schema_validate("structure", structure)
    return PaginatedBook(pages=pages, structure=structure, chapters=layouts)
