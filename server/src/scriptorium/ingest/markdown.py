"""Markdown / paste adapter (DESIGN §5.2).

Headings become chapter breaks: the first heading level that appears at least
twice is the chapter level; that heading's text is the chapter title. The leading
``#`` may be followed by a space or not (``# Chapter`` and ``#Chapter`` both count) —
non-technical users paste both forms. Body is split on blank lines into paragraphs;
other markdown syntax is passed through as plain text (v1, no rendering). A leading
``---`` YAML front-matter block is honored for ``title``/``author``/``language``/``era``
when present.

Front-matter is parsed with a minimal scalar ``key: value`` reader rather than a
YAML dependency: the honored keys are all simple strings, so a full YAML parser
would be unused weight. Nested/typed front-matter is out of scope for v1.
"""

from __future__ import annotations

import re

from . import base
from .base import (
    KIND_MARKDOWN,
    SOURCE_USER,
    WARN_CHAPTERS_UNDETECTED,
    Chapter,
    RawBook,
    SourceSpec,
    normalize_source_text,
    read_source,
    split_paragraphs,
    user_book_id,
)
from .base import _chapters_from_headings as _segment

# The space after ``#`` is optional: ``# Chapter`` and ``#Chapter`` both parse as headings.
# Anchored ``^`` keeps it from matching a mid-line ``#``.
_HEADING = re.compile(r"^(#{1,6})\s*(.+?)\s*#*\s*$")
_FRONT_MATTER_KEYS = {"title", "author", "language", "era"}


def _parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    """Split a leading ``---`` block from the body; return (fields, body).

    ``text`` must already be newline-normalized. Only simple ``key: value`` scalar
    lines are read; unknown keys are ignored. No closing fence → no front-matter.
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            fields: dict[str, str] = {}
            for raw in lines[1:i]:
                if ":" in raw:
                    key, value = raw.split(":", 1)
                    key = key.strip().lower()
                    if key in _FRONT_MATTER_KEYS:
                        fields[key] = value.strip().strip("\"'")
            return fields, "\n".join(lines[i + 1 :])
    return {}, text


def _split_markdown_chapters(
    body: str, book_title: str | None
) -> tuple[list[Chapter], list[str]]:
    lines = body.split("\n")
    headings: list[tuple[int, int, str]] = []  # (line_index, level, title)
    for i, line in enumerate(lines):
        m = _HEADING.match(line)
        if m:
            headings.append((i, len(m.group(1)), m.group(2).strip()))

    counts: dict[int, int] = {}
    order: list[int] = []
    for _, level, _title in headings:
        counts[level] = counts.get(level, 0) + 1
        if level not in order:
            order.append(level)
    chapter_level = next((lv for lv in order if counts[lv] >= 2), None)

    if chapter_level is None:
        return [Chapter(title=book_title, paragraphs=split_paragraphs(body))], [
            WARN_CHAPTERS_UNDETECTED
        ]

    chapter_heads = [(i, title) for (i, level, title) in headings if level == chapter_level]
    return _segment(lines, chapter_heads), []


def load(spec: SourceSpec) -> RawBook:
    """Ingest markdown into a :class:`RawBook` (§5.2)."""
    raw, _filename = read_source(spec)
    normalized = normalize_source_text(raw)
    fields, body = _parse_front_matter(normalized)

    title = spec.title or fields.get("title")
    author = spec.author or fields.get("author")
    language = spec.language or fields.get("language")
    era = fields.get("era")

    chapters, warnings = _split_markdown_chapters(body, title)
    return RawBook(
        book_id=user_book_id(normalized),
        source_kind=SOURCE_USER,
        chapters=chapters,
        title=title,
        author=author,
        language=language,
        era=era,
        warnings=warnings,
    )


base.register(KIND_MARKDOWN, load)
