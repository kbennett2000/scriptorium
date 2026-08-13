"""Dev CLI shim for eyeballing ingestion output (BUILD-PLAN §S2 acceptance).

    uv run python -m scriptorium.ingest --file <path> --kind text
    uv run python -m scriptorium.ingest --gutenberg-id 35 --kind gutenberg
    uv run python -m scriptorium.ingest --search "time machine"

Not a production interface — it prints book id, metadata, chapter count/titles,
and any warnings for a human to sanity-check an adapter.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

from ..config import load_config
from . import gutenberg
from .base import KIND_GUTENBERG, KIND_MARKDOWN, KIND_TEXT, SourceSpec, load


def _print_book(spec: SourceSpec) -> None:
    book = load(spec)
    print(f"book_id     : {book.book_id}")
    print(f"source_kind : {book.source_kind}")
    print(f"title       : {book.title}")
    print(f"author      : {book.author}")
    print(f"language    : {book.language}")
    if book.era:
        print(f"era         : {book.era}")
    print(f"warnings    : {book.warnings or 'none'}")
    print(f"chapters    : {len(book.chapters)}")
    for i, chapter in enumerate(book.chapters, 1):
        words = sum(len(p.split()) for p in chapter.paragraphs)
        print(f"  {i:>3}. {chapter.title!r:<28} ({len(chapter.paragraphs)} paras, {words} words)")


def _print_search(query: str) -> None:
    bases = gutenberg.gutendex_bases(load_config().gutendex_url)
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        for hit in gutenberg.search(query, client=client, bases=bases):
            print(f"  pg-{hit['gutenberg_id']:<7} {hit['title']} — {hit['author']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scriptorium.ingest")
    parser.add_argument("--file", type=Path, help="path to a .txt/.md source")
    parser.add_argument(
        "--kind", choices=[KIND_GUTENBERG, KIND_TEXT, KIND_MARKDOWN], default=KIND_TEXT
    )
    parser.add_argument("--gutenberg-id", type=int, help="Gutenberg book id (kind=gutenberg)")
    parser.add_argument("--search", help="search Gutendex and list hits, then exit")
    args = parser.parse_args(argv)

    if args.search:
        _print_search(args.search)
        return 0

    if args.kind == KIND_GUTENBERG:
        if args.gutenberg_id is None:
            parser.error("--kind gutenberg requires --gutenberg-id")
        spec = SourceSpec(kind=KIND_GUTENBERG, gutenberg_id=args.gutenberg_id)
    else:
        if args.file is None:
            parser.error("--kind text/markdown requires --file")
        spec = SourceSpec(kind=args.kind, path=args.file, filename=args.file.name)

    _print_book(spec)
    return 0


if __name__ == "__main__":
    sys.exit(main())
