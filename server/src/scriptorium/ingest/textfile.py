"""Plain-text / paste adapter (DESIGN §5.3).

An uploaded or pasted ``.txt`` (or sideloaded file) runs through the same chapter
heuristics as the Gutenberg adapter, but with ``source.kind: "user"`` and a
``usr-`` id derived from the text. PG boilerplate is *not* stripped here — that is
scoped to the gutenberg adapter (DESIGN §5.1); a sideloaded PG file keeps its
boilerplate unless ingested as ``kind: gutenberg``.
"""

from __future__ import annotations

from . import base
from .base import (
    KIND_TEXT,
    SOURCE_USER,
    RawBook,
    SourceSpec,
    detect_chapters,
    normalize_source_text,
    read_source,
    user_book_id,
)


def load(spec: SourceSpec) -> RawBook:
    """Ingest plain text into a :class:`RawBook` (§5.3)."""
    raw, _filename = read_source(spec)
    normalized = normalize_source_text(raw)
    chapters, warnings = detect_chapters(normalized, spec.title)
    return RawBook(
        book_id=user_book_id(normalized),
        source_kind=SOURCE_USER,
        chapters=chapters,
        title=spec.title,
        author=spec.author,
        language=spec.language,
        warnings=warnings,
    )


base.register(KIND_TEXT, load)
