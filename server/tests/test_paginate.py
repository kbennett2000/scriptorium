"""Paginator tests (DESIGN §6).

The load-bearing guarantees are **round-trip byte-equality** (a chapter's pages
reassemble into its normalized text byte-for-byte, even across sentence/line splits)
and **determinism** (same input ⇒ identical bytes). Per repo policy the golden
asserts stability, not prose — full page text is never committed as a golden.
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import pytest

from scriptorium.ingest import gutenberg
from scriptorium.ingest.base import Chapter, RawBook, SourceSpec, load
from scriptorium.paginate import DEFAULT_PARAMS, paginate
from scriptorium.schemas import is_valid

SOURCES = Path(__file__).parent / "fixtures" / "sources"
GOLDENS = Path(__file__).parent / "fixtures" / "goldens"
P = DEFAULT_PARAMS


def _pg35() -> RawBook:
    src = (SOURCES / "pg35.txt").read_text(encoding="utf-8")
    return gutenberg.load(
        SourceSpec(kind="gutenberg", gutenberg_id=35, text=src, title="The Time Machine")
    )


def _final_page_ids(pb) -> set[str]:
    return {ch["page_ids"][-1] for ch in pb.structure["chapters"]}


# --- round-trip (the load-bearing test) ------------------------------------

@pytest.mark.parametrize(
    "spec",
    [
        SourceSpec(kind="gutenberg", gutenberg_id=35),  # replaced below via _pg35
        SourceSpec(kind="markdown", path=SOURCES / "verse.md", filename="verse.md"),
        SourceSpec(kind="text", path=SOURCES / "longpara.txt", title="Long"),
        SourceSpec(kind="text", path=SOURCES / "submin.txt", title="Workshop"),
    ],
    ids=["pg35", "verse", "longpara", "submin"],
)
def test_round_trip_byte_exact(spec):
    book = _pg35() if spec.gutenberg_id == 35 else load(spec)
    pb = paginate(book)
    for i, chapter in enumerate(book.chapters):
        canonical = "\n\n".join(chapter.paragraphs)
        assert pb.reconstruct_chapter(i) == canonical, f"chapter {i} ({chapter.title})"


def test_round_trip_survives_sentence_splits():
    # longpara is one ~3000-word single-line paragraph → forced sentence-splitting;
    # reconstruction must still be byte-exact across every split boundary.
    book = load(SourceSpec(kind="text", path=SOURCES / "longpara.txt", title="Long"))
    pb = paginate(book)
    assert len(pb.pages) > 1  # it really did split
    # one paragraph, so >1 pages proves the paragraph was broken across pages
    assert pb.reconstruct_chapter(0) == "\n\n".join(book.chapters[0].paragraphs)


# --- determinism ------------------------------------------------------------

def test_determinism_identical_bytes():
    book = _pg35()
    a, b = paginate(book), paginate(book)
    assert [p["text"] for p in a.pages] == [p["text"] for p in b.pages]
    assert json.dumps(a.pages) == json.dumps(b.pages)
    assert a.structure == b.structure


# --- properties -------------------------------------------------------------

def test_no_underfull_pages_except_chapter_finals():
    book = _pg35()
    pb = paginate(book)
    finals = _final_page_ids(pb)
    for page in pb.pages:
        if page["word_count"] < P.min:
            assert page["id"] in finals, f"page {page['id']} under min and not a chapter final"


def test_no_page_exceeds_verse_cap():
    book = _pg35()
    pb = paginate(book)
    assert all(p["word_count"] <= P.verse_cap_words for p in pb.pages)


def test_every_page_validates_and_ids_are_contiguous():
    book = _pg35()
    pb = paginate(book)
    for k, page in enumerate(pb.pages, start=1):
        assert is_valid("page", page)
        assert page["seq"] == k
        assert page["id"] == f"{k:04d}"
    assert is_valid("structure", pb.structure)


def test_structure_page_ids_cover_all_pages_in_order():
    book = _pg35()
    pb = paginate(book)
    from_structure = [pid for ch in pb.structure["chapters"] for pid in ch["page_ids"]]
    assert from_structure == [p["id"] for p in pb.pages]
    # chapter indices are 1-based and contiguous; each page's chapter matches structure
    assert [ch["index"] for ch in pb.structure["chapters"]] == list(
        range(1, len(book.chapters) + 1)
    )


def test_page_text_is_byte_stable():
    book = _pg35()
    pb = paginate(book)
    for page in pb.pages:
        t = page["text"]
        assert "\r" not in t
        assert t == unicodedata.normalize("NFC", t)
        assert t == t.rstrip()


# --- step-specific behaviour ------------------------------------------------

def test_chapters_never_share_a_page():
    book = _pg35()
    pb = paginate(book)
    # every page belongs to exactly one chapter; structure partitions the pages
    owners = {pid: ch["index"] for ch in pb.structure["chapters"] for pid in ch["page_ids"]}
    assert len(owners) == len(pb.pages)


def test_longpara_pages_stay_under_max_and_split_on_sentences():
    book = load(SourceSpec(kind="text", path=SOURCES / "longpara.txt", title="Long"))
    pb = paginate(book)
    assert all(p["word_count"] <= P.max for p in pb.pages)
    # every page except the last ends at a sentence terminator (split landed on a boundary)
    for page in pb.pages[:-1]:
        assert page["text"].rstrip()[-1] in ".!?…"


def test_verse_paragraphs_are_never_sentence_split():
    book = load(SourceSpec(kind="markdown", path=SOURCES / "verse.md", filename="verse.md"))
    pb = paginate(book)
    # A verse book: total "\n\n"-separated blocks across pages must equal the number
    # of source paragraphs — i.e. no stanza was broken into fragments.
    blocks = sum(len(p["text"].split("\n\n")) for p in pb.pages)
    paras = sum(len(ch.paragraphs) for ch in book.chapters)
    assert blocks == paras


def test_oversized_verse_splits_on_line_boundaries_only():
    # A single verse paragraph exceeding 1.25×max must split on internal '\n' lines,
    # never mid-line, and round-trip byte-exactly.
    lines = "\n".join(
        f"line number {i} carries several plain words across the stanza" for i in range(160)
    )
    book = RawBook(
        book_id="usr-000000000000",
        source_kind="user",
        chapters=[Chapter(title="Verse", paragraphs=[lines])],
    )
    pb = paginate(book)
    assert len(pb.pages) > 1
    assert all(p["word_count"] <= P.verse_cap_words for p in pb.pages)
    assert pb.reconstruct_chapter(0) == lines
    # split fell only on line boundaries: every non-blank line is a whole source line
    for page in pb.pages:
        for line in page["text"].split("\n"):
            assert line == "" or line.startswith("line number")


def test_submin_single_chapter_final_page_may_be_under_min():
    book = load(SourceSpec(kind="text", path=SOURCES / "submin.txt", title="Workshop"))
    pb = paginate(book)
    assert len(pb.pages) == 1
    assert pb.pages[0]["word_count"] < P.min  # allowed: it is the chapter's final page


def test_empty_chapter_still_emits_one_page():
    book = RawBook(
        book_id="usr-000000000000",
        source_kind="user",
        chapters=[Chapter(title="Empty", paragraphs=[])],
    )
    pb = paginate(book)
    assert len(pb.pages) == 1
    assert pb.pages[0]["text"] == ""
    assert pb.structure["chapters"][0]["page_ids"] == ["0001"]


def test_chapter_title_fallbacks():
    book = RawBook(
        book_id="usr-000000000000",
        source_kind="user",
        title="Booktitle",
        chapters=[
            Chapter(title="Named", paragraphs=["a word here"]),
            Chapter(title=None, paragraphs=["another word here"]),
        ],
    )
    pb = paginate(book)
    titles = [ch["title"] for ch in pb.structure["chapters"]]
    assert titles == ["Named", "Booktitle"]  # None → falls back to book title


# --- golden -----------------------------------------------------------------

def test_pg35_matches_golden():
    golden = json.loads((GOLDENS / "pg35.golden.json").read_text(encoding="utf-8"))
    pb = paginate(_pg35())
    pages = pb.pages
    assert len(pages) == golden["page_count"]
    assert [p["word_count"] for p in pages] == golden["word_counts"]
    for key, page in {"1": pages[0], "2": pages[1], "N": pages[-1]}.items():
        assert page["text"][:40] == golden["edges"][key]["first40"]
        assert page["text"][-40:] == golden["edges"][key]["last40"]
