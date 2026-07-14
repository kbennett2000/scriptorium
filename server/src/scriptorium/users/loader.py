"""Household-profiles loader (DESIGN §14, ADR-0005).

``users.json`` is a top-level array of passwordless ``{id, name, color}`` profiles that the reader's
first-run picker and the sync namespacing both key off. It is hand-edited on the i5 in v1 (admin
CRUD is a §14 stretch goal, out of scope for S12).

On a fresh box the file may not exist yet, so the loader falls back to a **committed dev sample**
(:data:`_SAMPLE`) — this keeps ``GET /api/users`` useful out of the box and lets tests exercise the
endpoint without seeding. Either source is validated against the ``users`` schema before it is
returned, so a malformed hand-edit surfaces as an error rather than reaching the reader.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import schemas
from ..config import Config

_SAMPLE = Path(__file__).parent / "users.sample.json"


def load_users(cfg: Config) -> list[dict[str, Any]]:
    """Return the household profiles, validated against the ``users`` schema.

    Reads ``cfg.users_file`` if it exists, otherwise the committed sample. Raises
    ``jsonschema.ValidationError`` if the resolved source does not match the schema (the endpoint
    turns that into a 500-with-context rather than silently serving garbage).
    """
    source = cfg.users_file if cfg.users_file.is_file() else _SAMPLE
    data = json.loads(source.read_text(encoding="utf-8"))
    schemas.validate("users", data)
    return data
