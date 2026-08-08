"""Ingestion interface, registry, and shared parsing utilities (DESIGN §5).

An *adapter* turns a :class:`SourceSpec` into a :class:`RawBook` — the internal,
pre-pagination representation every later cycle consumes:

    RawBook = {title?, author?, language?, chapters: [{title?, paragraphs: [str]}]}

A paragraph is a *display unit*. Internal newlines are preserved verbatim: verse
stanzas keep their line breaks (DESIGN §5), and prose keeps its source hard-wrap —
harmless because the reader renders prose with ``white-space: normal`` (newlines
collapse to spaces) and verse with ``white-space: pre-line``. Keeping the bytes
here makes RawBook a lossless capture and defers all reflow to display time.

Book ids follow DESIGN §4.1: ``pg-{gutenberg_id}`` for Gutenberg, and
``usr-{first 12 hex of sha256 of the normalized source text}`` for user content.
Ids are permanent, so the normalization hashed here is a frozen contract.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

# --- Source kinds (the admin request `kind`, DESIGN §5.3) -------------------
KIND_GUTENBERG = "gutenberg"
KIND_TEXT = "text"
KIND_MARKDOWN = "markdown"

# --- Bundle-level source origin (meta.source.kind, DESIGN §5.3 / S1) --------
SOURCE_GUTENBERG = "gutenberg"
SOURCE_USER = "user"

# --- Job warnings (DESIGN §5.1) --------------------------------------------
WARN_BOILERPLATE_UNSTRIPPED = "boilerplate_unstripped"
WARN_CHAPTERS_UNDETECTED = "chapters_undetected"


@dataclass(frozen=True)
class SourceSpec:
    """A request to ingest one source.

    Exactly one payload is used per ``kind``: ``gutenberg_id`` for the gutenberg
    adapter, otherwise ``text`` (pasted) or ``path`` (an uploaded/sideloaded file).
    ``title``/``author``/``language`` optionally override detected metadata.
    """

    kind: str
    gutenberg_id: int | None = None
    path: Path | None = None
    text: str | None = None
    filename: str | None = None
    title: str | None = None
    author: str | None = None
    language: str | None = None


@dataclass(frozen=True)
class Chapter:
    """One chapter: an optional title and its display paragraphs."""

    title: str | None
    paragraphs: list[str]


@dataclass
class RawBook:
    """The ingestion result — internal, validated by shape not by JSON Schema.

    ``era`` extends DESIGN's minimal RawBook shape: markdown front-matter may supply
    an era (DESIGN §5.2) whose real home is bake config (meta.era, §4.3). Capturing
    it here keeps a user-provided value from being silently dropped before S9.
    """

    book_id: str
    source_kind: str  # SOURCE_GUTENBERG | SOURCE_USER (matches meta.source.kind)
    chapters: list[Chapter]
    title: str | None = None
    author: str | None = None
    language: str | None = None
    era: str | None = None
    warnings: list[str] = field(default_factory=list)


# --- Text normalization & identity (DESIGN §4.1) ---------------------------

def normalize_source_text(text: str) -> str:
    """Canonicalize source text for hashing and parsing.

    Newlines are unified to ``\\n`` (``\\r\\n`` and lone ``\\r`` collapse) and the
    result is Unicode NFC. This is the exact form whose sha256 yields the ``usr-``
    id, so it is a permanent contract — do not change it without a bundle-version
    bump. Aligns with the paginator's NFC + ``\\n`` normalization (S3).
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFC", text)


def user_book_id(normalized_text: str) -> str:
    """``usr-`` id from already-normalized source text (DESIGN §4.1)."""
    digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
    return f"usr-{digest[:12]}"


def gutenberg_book_id(gutenberg_id: int) -> str:
    """``pg-{id}`` id for a Gutenberg book (DESIGN §4.1)."""
    return f"pg-{gutenberg_id}"


def read_source(spec: SourceSpec) -> tuple[str, str]:
    """Return ``(text, filename)`` for a user source (pasted ``text`` or ``path``)."""
    if spec.text is not None:
        return spec.text, spec.filename or "source.txt"
    if spec.path is not None:
        return spec.path.read_text(encoding="utf-8"), spec.filename or spec.path.name
    raise ValueError("user source requires text or path")


# --- Paragraph splitting ----------------------------------------------------

_BLANK_LINE = re.compile(r"\n[ \t]*\n")


def split_paragraphs(text: str) -> list[str]:
    """Split ``text`` into paragraphs on blank-line runs.

    Internal newlines within a block are preserved (verse stanzas stay one
    paragraph). Trailing whitespace is trimmed per line and empty blocks dropped.
    """
    paragraphs: list[str] = []
    for block in _BLANK_LINE.split(text):
        lines = [line.rstrip() for line in block.split("\n")]
        para = "\n".join(lines).strip("\n")
        if para.strip():
            paragraphs.append(para)
    return paragraphs


# --- Chapter detection (DESIGN §5.1 heuristics 1–3, applied in order) -------

# Numbered heading. The divider keywords are matched in both ALL-CAPS and Title case so a
# Gutenberg book that writes "Book II. An Unfortunate Gathering" (Title case) registers a
# boundary just like "CHAPTER I". The numeral is kept UPPER-Roman/digit to avoid catching a
# lowercase prose line ("part i was my favourite").
_H1 = re.compile(r"^(CHAPTER|Chapter|BOOK|Book|PART|Part|CANTO|Canto)\s+([IVXLC]+|\d+)\b.*$")
_H2 = re.compile(r"^[IVXLC]+\.?$")
# A section divider names a Part of the work but carries no chapter numeral (e.g.
# "Book the Second--the Golden Thread"), so the numbered heuristics never see it.
_SECTION = re.compile(r"^(BOOK|PART|CANTO|VOLUME)\b", re.IGNORECASE)
# Named structural sections that carry no numeral (Epilogue, Prologue, Footnotes, …). Used to
# recognise such a line as "heading-shaped" (see _is_headingish) so a dense contents list whose
# entries swallow an "Epilogue"/"Footnotes" line contributes no prose and is pruned as junk. It
# is deliberately NOT a chapter boundary: making it one would re-segment existing books that end
# in an Epilogue (e.g. pg35 The Time Machine) and drift their byte-stable pagination.
_SECTION_WORD = re.compile(
    r"^(EPILOGUE|PROLOGUE|FOREWORD|AFTERWORD|CONCLUSION|FOOTNOTES?)\b", re.IGNORECASE
)


def _headings_h1(lines: list[str]) -> list[tuple[int, str]]:
    """Heuristic 1: ``CHAPTER/BOOK/PART/CANTO <numeral>`` lines."""
    out = []
    for i, raw in enumerate(lines):
        line = raw.strip()
        if _H1.match(line):
            out.append((i, line))
    return out


def _headings_h2(lines: list[str]) -> list[tuple[int, str]]:
    """Heuristic 2: standalone Roman-numeral lines (title = numeral, no dot)."""
    out = []
    for i, raw in enumerate(lines):
        line = raw.strip()
        if _H2.match(line):
            out.append((i, line.rstrip(".")))
    return out


def _headings_h3(lines: list[str]) -> list[tuple[int, str]]:
    """Heuristic 3: standalone ALL-CAPS lines <=60 chars between blank lines."""
    out = []
    last = len(lines) - 1
    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line or len(line) > 60:
            continue
        if line.upper() != line or line.lower() == line:
            continue  # not cased-uppercase (needs at least one letter)
        above_blank = i == 0 or lines[i - 1].strip() == ""
        below_blank = i == last or lines[i + 1].strip() == ""
        if above_blank and below_blank:
            out.append((i, line))
    return out


def _section_headings(lines: list[str]) -> list[tuple[int, str]]:
    """Standalone section-divider lines like ``Book the Second--the Golden Thread``.

    These name a Part of the work but have no chapter numeral, so the numbered
    heuristics miss them. Require a short line bracketed by blank lines (as in H3) so a
    prose sentence beginning ``Part of…`` is never mistaken for a divider.
    """
    out = []
    last = len(lines) - 1
    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line or len(line) > 60 or not _SECTION.match(line):
            continue
        above_blank = i == 0 or lines[i - 1].strip() == ""
        below_blank = i == last or lines[i + 1].strip() == ""
        if above_blank and below_blank:
            out.append((i, line))
    return out


def _merge_headings(
    numbered: list[tuple[int, str]], dividers: list[tuple[int, str]]
) -> list[tuple[int, str]]:
    """Union numbered headings with section dividers, ordered by line index."""
    seen = {i for i, _ in numbered}
    merged = list(numbered) + [(i, t) for i, t in dividers if i not in seen]
    merged.sort(key=lambda pair: pair[0])
    return merged


def _chapters_from_headings(
    lines: list[str], headings: list[tuple[int, str]]
) -> list[Chapter]:
    """Segment ``lines`` into chapters at the given heading indices.

    Content before the first heading (title page, table of contents) is dropped.
    """
    chapters: list[Chapter] = []
    for n, (idx, title) in enumerate(headings):
        start = idx + 1
        end = headings[n + 1][0] if n + 1 < len(headings) else len(lines)
        body = "\n".join(lines[start:end])
        chapters.append(Chapter(title=title, paragraphs=split_paragraphs(body)))
    return chapters


def _is_part_divider(title: str | None) -> bool:
    """A ``BOOK``/``PART``/``CANTO``/``VOLUME`` label — a section, not a numbered chapter."""
    return bool(title) and bool(_SECTION.match(title.strip()))


def _is_headingish(line: str) -> bool:
    """True if ``line`` looks like a heading rather than prose.

    Covers every heading shape the detectors use — numbered (``_H1``), standalone Roman
    (``_H2``), section dividers (``_SECTION``), named sections (``_SECTION_WORD``), and the
    ALL-CAPS-short H3 shape — so a table-of-contents entry that swallowed a lone
    ``"Book II. …"`` / ``"Epilogue"`` line contributes **no** prose (see
    :func:`_prose_word_count`).
    """
    line = line.strip()
    if not line:
        return False
    if _H1.match(line) or _H2.match(line) or _SECTION.match(line) or _SECTION_WORD.match(line):
        return True
    # Standalone ALL-CAPS short line (the H3 shape, minus its blank-line-bracket context).
    return len(line) <= 60 and line.upper() == line and line.lower() != line


def _prose_word_count(paragraphs: list[str]) -> int:
    """Count words on the non-blank, non-heading-shaped lines of ``paragraphs``.

    This is the discriminator between a real chapter (has actual prose/verse) and a
    contents-list artifact (whose only "body" is another heading-shaped line). It is
    deliberately length-agnostic: a one-sentence chapter still has prose > 0.
    """
    return sum(
        len(line.split())
        for para in paragraphs
        for line in para.split("\n")
        if line.strip() and not _is_headingish(line)
    )


def _fold(pending: str | None, title: str | None) -> str | None:
    """Join a pending Part/Book label with a title (either may be ``None``)."""
    if pending and title:
        return f"{pending} — {title}"
    return pending or title


def _prune_headings(chapters: list[Chapter]) -> list[Chapter]:
    """Drop table-of-contents artifacts and fold Part-divider labels into real chapters.

    ``_H1`` matches every ``CHAPTER/BOOK <numeral> <title>`` line, so a book that prints its
    own table of contents yields a run of *bodyless* (or near-empty) chapters — one per
    contents line — junk that later becomes a blank/near-empty page and a hallucinated
    illustration. A dense contents list (Gutenberg's *Brothers Karamazov*) additionally lets a
    ``"Book II. …"`` / ``"Epilogue"`` line get swallowed as the *tiny* body of a preceding
    contents entry, so a plain "has any paragraph" test is not enough. Walk the detected
    chapters and:

    - keep every chapter with real **prose** (``_prose_word_count > 0``), folding any pending
      Part/Book label(s) into its title;
    - hold a **prose-free** ``BOOK``/``PART``/``CANTO`` heading as a *pending* label, stacking
      Part+Book (e.g. ``"PART I — Book II. …"``) — it survives only if the next chapter is a
      real one (a real divider sits just before its section's first chapter; a contents-list
      divider is followed by more prose-free lines, which clear it);
    - drop any other prose-free heading (a contents entry / stray title) and clear pending.
    """
    pruned: list[Chapter] = []
    pending: str | None = None
    for ch in chapters:
        if _prose_word_count(ch.paragraphs) > 0:
            pruned.append(Chapter(title=_fold(pending, ch.title), paragraphs=ch.paragraphs))
            pending = None
        elif _is_part_divider(ch.title):
            pending = _fold(pending, ch.title)  # stack Part + Book; kept only before a real chapter
        else:
            pending = None  # a prose-free contents entry / stray heading → discard
    return pruned


def detect_chapters(
    text: str, book_title: str | None = None
) -> tuple[list[Chapter], list[str]]:
    """Detect chapters via heuristics 1→2→3; first yielding >=2 chapters wins.

    All heuristics failing → a single chapter titled by the book and a
    ``chapters_undetected`` warning (DESIGN §5.1; the S9 admin chapter editor
    lets a human fix breaks pre-bake).
    """
    lines = text.split("\n")
    dividers = _section_headings(lines)
    for detector in (_headings_h1, _headings_h2, _headings_h3):
        headings = detector(lines)
        if len(headings) >= 2:
            merged = _merge_headings(headings, dividers)
            chapters = _prune_headings(_chapters_from_headings(lines, merged))
            if len(chapters) >= 2:
                return chapters, []
            break  # headings were all front-matter/contents junk → single-chapter fallback
    return [Chapter(title=book_title, paragraphs=split_paragraphs(text))], [
        WARN_CHAPTERS_UNDETECTED
    ]


# --- Raw-source archival (DESIGN §5.1 provenance) --------------------------

def archive_source(
    work_dir: Path, book_id: str, filename: str, raw_bytes: bytes
) -> Path:
    """Write the raw source to ``work/{book_id}/source/{filename}`` and return it.

    Kept out of the pure ``load`` path so parsing stays side-effect-free; called by
    the CLI shim and (later) the job runner.
    """
    dest = work_dir / book_id / "source" / filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw_bytes)
    return dest


# --- Adapter registry -------------------------------------------------------

Adapter = Callable[[SourceSpec], RawBook]
ADAPTERS: dict[str, Adapter] = {}


def register(kind: str, adapter: Adapter) -> None:
    """Register ``adapter`` for a source ``kind``."""
    ADAPTERS[kind] = adapter


_registered = False


def _ensure_registered() -> None:
    global _registered
    if _registered:
        return
    # Import for side-effect registration; done lazily to avoid import cycles.
    from . import gutenberg, markdown, textfile  # noqa: F401

    _registered = True


def load(spec: SourceSpec) -> RawBook:
    """Dispatch to the adapter registered for ``spec.kind``."""
    _ensure_registered()
    adapter = ADAPTERS.get(spec.kind)
    if adapter is None:
        raise ValueError(
            f"unknown source kind {spec.kind!r}; expected one of {sorted(ADAPTERS)}"
        )
    return adapter(spec)
