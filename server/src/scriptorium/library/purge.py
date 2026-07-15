"""Permanent book deletion — owner-initiated library management.

Removes **everything** a book owns across the data tree: its published bundle (``library/{book}``),
its bake work tree (``work/{book}``), its job records (the book job ``jobs/{book}.json`` plus any
set-render jobs ``jobs/{book}#*.json``), **every** profile's private picture sets for it
(``artsets/{user}/{book}``), and **every** profile's sync data for it (annotations, positions, and
annotation backups under ``sync/*/{user}/{book}``).

This is the single place the system destroys a published bundle. That does not weaken the
immutability guard, which forbids *mutating* a published book's page text/structure (revisions stay
additive); a whole-book delete removes the book outright, a deliberate, confirmed owner action.
Idempotent per path: a path that isn't there is simply skipped.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from ..config import Config

_BOOK_RE = re.compile(r"^(pg-[0-9]+|usr-[0-9a-f]{12})$")


def _rm(path: Path, removed: list[str], root: Path) -> None:
    """Remove a file or directory tree, recording its data-relative path. No-op if absent."""
    if path.is_dir():
        shutil.rmtree(path)
    elif path.is_file():
        path.unlink()
    else:
        return
    removed.append(path.relative_to(root).as_posix())


def purge_book(cfg: Config, book_id: str) -> list[str]:
    """Delete every trace of ``book_id`` under ``cfg.data_dir``; return the removed paths.

    Raises ``ValueError`` on a malformed ``book_id`` (the caller has already validated existence).
    """
    if not _BOOK_RE.match(book_id):
        raise ValueError(f"bad book id {book_id!r}")
    root = cfg.data_dir
    removed: list[str] = []

    # Published bundle + bake work tree.
    _rm(cfg.library_dir / book_id, removed, root)
    _rm(cfg.work_dir / book_id, removed, root)

    # Job records: the book's own job + any set-render jobs ({book}#{set_id}.json).
    if cfg.jobs_dir.is_dir():
        _rm(cfg.jobs_dir / f"{book_id}.json", removed, root)
        for p in sorted(cfg.jobs_dir.glob(f"{book_id}#*.json")):
            _rm(p, removed, root)

    # Every profile's private picture sets for this book.
    if cfg.artsets_dir.is_dir():
        for user_dir in sorted(cfg.artsets_dir.iterdir()):
            if user_dir.is_dir():
                _rm(user_dir / book_id, removed, root)

    # Every profile's sync data for this book (annotations/positions .json + backup dirs).
    if cfg.sync_dir.is_dir():
        for kind_dir in sorted(cfg.sync_dir.iterdir()):
            if not kind_dir.is_dir():
                continue
            for user_dir in sorted(kind_dir.iterdir()):
                if not user_dir.is_dir():
                    continue
                _rm(user_dir / f"{book_id}.json", removed, root)
                _rm(user_dir / book_id, removed, root)

    return removed
