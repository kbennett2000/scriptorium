"""Ingestion adapter tests (DESIGN §5).

Offline by default: the committed fixtures under ``fixtures/sources/`` are the test
diet, Gutendex HTTP is respx-mocked, and the one live-network test is ``-m network``
(deselected unless explicitly run). Per repo policy we never assert exact prose —
only counts, ranges, shapes, first-title plausibility, and warning flags.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from scriptorium.ingest import gutenberg
from scriptorium.ingest.base import (
    SOURCE_GUTENBERG,
    SOURCE_USER,
    WARN_BOILERPLATE_UNSTRIPPED,
    WARN_CHAPTERS_UNDETECTED,
    SourceSpec,
    detect_chapters,
    load,
    normalize_source_text,
    split_paragraphs,
    user_book_id,
)

SOURCES = Path(__file__).parent / "fixtures" / "sources"


def _read(name: str) -> str:
    return (SOURCES / name).read_text(encoding="utf-8")


# --- normalization & identity ----------------------------------------------

def test_normalize_unifies_newlines_and_nfc():
    assert normalize_source_text("a\r\nb\rc") == "a\nb\nc"
    # NFC: composed é vs decomposed e + combining acute collapse to one form.
    assert normalize_source_text("é") == normalize_source_text("é")


def test_user_id_is_stable_and_content_addressed():
    text = _read("headerless.txt")
    id1 = user_book_id(normalize_source_text(text))
    id2 = user_book_id(normalize_source_text(text))
    assert id1 == id2
    assert id1.startswith("usr-") and len(id1) == len("usr-") + 12
    other = user_book_id(normalize_source_text(text + " and one more sentence."))
    assert other != id1


def test_load_same_text_yields_same_id():
    spec = SourceSpec(kind="text", text=_read("allcaps.txt"))
    assert load(spec).book_id == load(spec).book_id


# --- paragraph splitting ----------------------------------------------------

def test_split_paragraphs_preserves_verse_newlines():
    text = "line one\nline two\n\nnext para"
    paras = split_paragraphs(text)
    assert paras == ["line one\nline two", "next para"]


def test_split_paragraphs_drops_blank_blocks():
    assert split_paragraphs("\n\n  \n\nonly\n\n\n") == ["only"]


# --- chapter heuristics (assert ranges / first title, not full lists) ------

def test_heuristic1_chapter_headings():
    # pg_markers via gutenberg: boilerplate stripped, then CHAPTER I/II (H1) win.
    book = gutenberg.load(
        SourceSpec(kind="gutenberg", gutenberg_id=99, text=_read("pg_markers.txt"))
    )
    assert len(book.chapters) == 2
    assert book.chapters[0].title == "CHAPTER I"
    assert WARN_BOILERPLATE_UNSTRIPPED not in book.warnings


def test_heuristic2_roman_numerals_pg35():
    book = gutenberg.load(
        SourceSpec(kind="gutenberg", gutenberg_id=35, text=_read("pg35.txt"),
                   title="The Time Machine")
    )
    assert len(book.chapters) >= 10
    assert book.chapters[0].title == "I"
    assert book.warnings == []


def test_heuristic3_allcaps():
    chapters, warnings = detect_chapters(normalize_source_text(_read("allcaps.txt")))
    assert len(chapters) == 3
    assert chapters[0].title == "THE GATHERING STORM"
    assert warnings == []


def test_heuristics_applied_in_order_first_win():
    # A file with both a CHAPTER line and standalone Roman lines: H1 must win.
    text = "CHAPTER 1\n\nbody one\n\nII\n\nbody two\n\nCHAPTER 2\n\nbody three\n"
    chapters, _ = detect_chapters(text)
    assert [c.title for c in chapters] == ["CHAPTER 1", "CHAPTER 2"]


# --- warnings ---------------------------------------------------------------

def test_missing_markers_sets_boilerplate_warning():
    stripped, warnings = gutenberg.strip_boilerplate(_read("headerless.txt"))
    assert warnings == [WARN_BOILERPLATE_UNSTRIPPED]
    assert stripped == _read("headerless.txt")


def test_markers_present_strips_license():
    raw = normalize_source_text(_read("pg_markers.txt"))
    stripped, warnings = gutenberg.strip_boilerplate(raw)
    assert warnings == []
    assert "trailing license text" not in stripped
    assert "Project Gutenberg eBook of" not in stripped
    assert "CHAPTER I" in stripped


def test_chapters_undetected_warning_single_chapter():
    book = load(SourceSpec(kind="text", text=_read("headerless.txt"), title="Marsh"))
    assert WARN_CHAPTERS_UNDETECTED in book.warnings
    assert len(book.chapters) == 1
    assert book.chapters[0].title == "Marsh"


# --- markdown ---------------------------------------------------------------

def test_markdown_front_matter_and_chapters():
    book = load(SourceSpec(kind="markdown", path=SOURCES / "frontmatter.md",
                           filename="frontmatter.md"))
    assert book.source_kind == SOURCE_USER
    assert book.title == "The Lantern Keeper"
    assert book.author == "Mara Vell"
    assert book.language == "en"
    assert book.era == "1920s coastal Maine"
    assert [c.title for c in book.chapters] == ["The Light", "The Fog", "The Wreck"]
    assert all(len(c.paragraphs) == 2 for c in book.chapters)


def test_markdown_spec_overrides_front_matter():
    book = load(SourceSpec(kind="markdown", path=SOURCES / "frontmatter.md",
                           filename="frontmatter.md", title="Override"))
    assert book.title == "Override"


# --- registry ---------------------------------------------------------------

def test_registry_dispatches_by_kind():
    text = load(SourceSpec(kind="text", text=_read("allcaps.txt")))
    assert text.source_kind == SOURCE_USER
    md = load(SourceSpec(kind="markdown", text=_read("frontmatter.md")))
    assert md.source_kind == SOURCE_USER


def test_unknown_kind_raises():
    with pytest.raises(ValueError):
        load(SourceSpec(kind="epub", text="x"))


# --- gutenberg network (respx-mocked) --------------------------------------

_TEXT_URL = "https://example.org/pg-sample.txt"
_MINI_PG = (
    "The Project Gutenberg eBook of Sample\n\n"
    "*** START OF THE PROJECT GUTENBERG EBOOK SAMPLE ***\n\n"
    "CHAPTER I\n\nfirst body.\n\nCHAPTER II\n\nsecond body.\n\n"
    "*** END OF THE PROJECT GUTENBERG EBOOK SAMPLE ***\n\nlicense.\n"
)
_BOOK_JSON = {
    "id": 35,
    "title": "The Time Machine",
    "authors": [{"name": "Wells, H. G."}],
    "languages": ["en"],
    "formats": {"text/plain; charset=utf-8": _TEXT_URL},
}


@respx.mock
def test_fetch_text_mocked():
    respx.get("https://gutendex.com/books/35").mock(
        return_value=httpx.Response(200, json=_BOOK_JSON)
    )
    respx.get(_TEXT_URL).mock(return_value=httpx.Response(200, text=_MINI_PG))
    with httpx.Client() as client:
        text, meta = gutenberg.fetch_text(35, client=client)
    assert meta == {
        "gutenberg_id": 35,
        "title": "The Time Machine",
        "author": "Wells, H. G.",
        "language": "en",
    }
    assert "CHAPTER I" in text


@respx.mock
def test_load_gutenberg_mocked_end_to_end():
    respx.get("https://gutendex.com/books/35").mock(
        return_value=httpx.Response(200, json=_BOOK_JSON)
    )
    respx.get(_TEXT_URL).mock(return_value=httpx.Response(200, text=_MINI_PG))
    book = gutenberg.load(SourceSpec(kind="gutenberg", gutenberg_id=35))
    assert book.book_id == "pg-35"
    assert book.source_kind == SOURCE_GUTENBERG
    assert book.title == "The Time Machine"
    assert [c.title for c in book.chapters] == ["CHAPTER I", "CHAPTER II"]
    assert book.warnings == []


@respx.mock
def test_search_mocked():
    respx.get("https://gutendex.com/books").mock(
        return_value=httpx.Response(200, json={"results": [_BOOK_JSON]})
    )
    with httpx.Client() as client:
        hits = gutenberg.search("time machine", client=client)
    assert hits[0]["gutenberg_id"] == 35
    assert hits[0]["text_url"] == _TEXT_URL


# --- live network (skipped by default) -------------------------------------

@pytest.mark.network
def test_live_gutendex_fetch():
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        text, meta = gutenberg.fetch_text(35, client=client)
    assert meta["gutenberg_id"] == 35
    assert meta["title"]
    assert len(text) > 1000
