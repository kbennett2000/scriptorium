"""Pagination (DESIGN §6).

The paginator turns a :class:`~scriptorium.ingest.base.RawBook` into byte-stable,
deterministic pages. See :mod:`scriptorium.paginate.engine`.
"""

from __future__ import annotations

from .engine import (
    DEFAULT_PARAMS,
    PaginatedBook,
    PaginationParams,
    paginate,
)

__all__ = [
    "DEFAULT_PARAMS",
    "PaginatedBook",
    "PaginationParams",
    "paginate",
]
