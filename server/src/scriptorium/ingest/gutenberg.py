"""Gutenberg adapter — the only networked ingestion path (DESIGN §5.1).

Catalog search and text fetch go through Gutendex (``https://gutendex.com``); the
admin UI calls these through the server, never the reader. Plain-text is fetched,
Project Gutenberg boilerplate stripped, and chapters detected with the shared
heuristics. The pure functions (:func:`strip_boilerplate`, chapter detection) are
the offline test diet; the network is a thin, respx-mockable wrapper.
"""

from __future__ import annotations

import re

import httpx

from ..config import load_config
from . import base
from .base import (
    KIND_GUTENBERG,
    SOURCE_GUTENBERG,
    WARN_BOILERPLATE_UNSTRIPPED,
    RawBook,
    SourceSpec,
    detect_chapters,
    gutenberg_book_id,
    normalize_source_text,
)

# Public fallback instance. ``GUTENDEX_BASE`` remains the historical default (kept so existing
# offline mocks that target it keep passing); ``gutendex_bases`` is the runtime source of truth.
GUTENDEX_PUBLIC = "https://gutendex.com"
GUTENDEX_BASE = GUTENDEX_PUBLIC


def gutendex_bases(primary: str | None) -> list[str]:
    """Ordered, de-duped bases: the configured instance first, public ``gutendex.com`` as fallback.

    The public instance has been flaky (search hangs), so a self-hosted LAN instance is preferred
    via ``GUTENDEX_URL``; both call sites still fall back to public when the primary errors or has
    no match. When ``primary`` is unset/public the list is just ``[public]`` (unchanged behavior).
    """
    out: list[str] = []
    for base_url in ((primary or GUTENDEX_PUBLIC).rstrip("/"), GUTENDEX_PUBLIC):
        if base_url not in out:
            out.append(base_url)
    return out

# START/END markers, tolerant of THE/THIS and casing (DESIGN §5.1).
_START = re.compile(
    r"^\*\*\*\s*START OF TH(?:E|IS) PROJECT GUTENBERG.*\*\*\*\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_END = re.compile(
    r"^\*\*\*\s*END OF TH(?:E|IS) PROJECT GUTENBERG.*\*\*\*\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def strip_boilerplate(text: str) -> tuple[str, list[str]]:
    """Return the text between the PG START/END markers.

    Markers absent (or out of order) → the whole text is returned with a
    ``boilerplate_unstripped`` warning so a human can trim it later (§5.1).
    """
    start = _START.search(text)
    end = _END.search(text)
    if start and end and end.start() > start.end():
        return text[start.end() : end.start()].strip("\n"), []
    return text, [WARN_BOILERPLATE_UNSTRIPPED]


def _pick_text_url(formats: dict[str, str]) -> str | None:
    """Prefer UTF-8 plain text, else any ``text/plain`` variant (§5.1)."""
    preferred = formats.get("text/plain; charset=utf-8")
    if preferred:
        return preferred
    for mime, url in formats.items():
        if mime.startswith("text/plain"):
            return url
    return None


def _author_name(book: dict) -> str | None:
    authors = book.get("authors") or []
    return authors[0].get("name") if authors else None


def _language(book: dict) -> str | None:
    languages = book.get("languages") or []
    return languages[0] if languages else None


def _search_one(query: str, base_url: str, client: httpx.Client) -> list[dict]:
    # Trailing slash: gutendex.com now 301-redirects /books?... -> /books/?... (the caller's
    # client follows redirects, but hit the canonical URL directly to avoid the extra hop).
    resp = client.get(f"{base_url}/books/", params={"search": query})
    resp.raise_for_status()
    hits = []
    for book in resp.json().get("results", []):
        hits.append(
            {
                "gutenberg_id": book.get("id"),
                "title": book.get("title"),
                "author": _author_name(book),
                "language": _language(book),
                "text_url": _pick_text_url(book.get("formats") or {}),
            }
        )
    return hits


def search(query: str, *, client: httpx.Client, bases: list[str] | None = None) -> list[dict]:
    """Search Gutendex; return simplified hits for the admin UI (§5.1).

    Tries ``bases`` in order (see :func:`gutendex_bases`): prefer the configured instance, fall
    back to public ``gutendex.com`` when a base errors *or* returns no match. Returns ``[]`` if any
    base responded (a real no-match); raises the last error only when every base errored.
    """
    last_exc: Exception | None = None
    any_ok = False
    for base_url in bases or [GUTENDEX_PUBLIC]:
        try:
            hits = _search_one(query, base_url, client)
        except Exception as exc:  # noqa: BLE001 - try the next base
            last_exc = exc
            continue
        any_ok = True
        if hits:
            return hits
    if any_ok:
        return []
    raise last_exc  # type: ignore[misc]  # unreachable unless a base was tried and all errored


def fetch_text(
    gutenberg_id: int, *, client: httpx.Client, bases: list[str] | None = None
) -> tuple[str, dict]:
    """Fetch a book's plain text + metadata from Gutendex (§5.1).

    Metadata is read from the first reachable base (prefer local, fall back to public); the text
    itself is then downloaded from the book's own ``formats`` URL (a gutenberg.org link).
    """
    book: dict | None = None
    last_exc: Exception | None = None
    for base_url in bases or [GUTENDEX_PUBLIC]:
        try:
            meta_resp = client.get(f"{base_url}/books/{gutenberg_id}")
            meta_resp.raise_for_status()
            book = meta_resp.json()
            break
        except Exception as exc:  # noqa: BLE001 - try the next base
            last_exc = exc
            continue
    if book is None:
        raise last_exc  # type: ignore[misc]  # every base errored
    text_url = _pick_text_url(book.get("formats") or {})
    if not text_url:
        raise ValueError(f"no text/plain format for Gutenberg book {gutenberg_id}")
    text_resp = client.get(text_url)
    text_resp.raise_for_status()
    meta = {
        "gutenberg_id": gutenberg_id,
        "title": book.get("title"),
        "author": _author_name(book),
        "language": _language(book),
    }
    return text_resp.text, meta


def load(spec: SourceSpec) -> RawBook:
    """Ingest a Gutenberg book into a :class:`RawBook` (§5.1).

    ``spec.text`` short-circuits the network (offline re-bake / sideload); otherwise
    the text is fetched live. Requires ``spec.gutenberg_id`` for the permanent id.
    """
    if spec.gutenberg_id is None:
        raise ValueError("gutenberg source requires gutenberg_id")

    if spec.text is not None:
        raw, meta = spec.text, {}
    else:
        bases = gutendex_bases(load_config().gutendex_url)
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            raw, meta = fetch_text(spec.gutenberg_id, client=client, bases=bases)

    normalized = normalize_source_text(raw)
    stripped, warnings = strip_boilerplate(normalized)

    title = spec.title or meta.get("title")
    author = spec.author or meta.get("author")
    language = spec.language or meta.get("language")

    chapters, chapter_warnings = detect_chapters(stripped, title)
    return RawBook(
        book_id=gutenberg_book_id(spec.gutenberg_id),
        source_kind=SOURCE_GUTENBERG,
        chapters=chapters,
        title=title,
        author=author,
        language=language,
        warnings=warnings + chapter_warnings,
    )


base.register(KIND_GUTENBERG, load)
