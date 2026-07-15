"""JSON Schema validation helper.

Single entry point used by every later cycle and by tests to validate bundle and
sync files against the normative schemas in ``shared/schemas``. See DESIGN §4.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

import jsonschema

from .config import load_config

# The schema kinds and their file names (all live in shared/schemas).
SCHEMA_KINDS: tuple[str, ...] = (
    "meta",
    "structure",
    "page",
    "cast",
    "selection",
    "prompt",
    "manifest",
    "annotations",
    "positions",
    "users",
    "styles",
    "artset",
    "artset-list",
)


def _schemas_dir() -> Path:
    return load_config().schemas_dir


@cache
def load_schema(kind: str) -> dict[str, Any]:
    """Load and cache the JSON Schema for ``kind``."""
    if kind not in SCHEMA_KINDS:
        raise ValueError(f"unknown schema kind {kind!r}; expected one of {SCHEMA_KINDS}")
    path = _schemas_dir() / f"{kind}.schema.json"
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


@cache
def _validator(kind: str) -> jsonschema.protocols.Validator:
    schema = load_schema(kind)
    cls = jsonschema.validators.validator_for(schema)
    cls.check_schema(schema)
    return cls(schema)


def validate(kind: str, obj: Any) -> None:
    """Validate ``obj`` against the schema for ``kind``.

    Raises ``jsonschema.ValidationError`` if invalid, ``ValueError`` if ``kind``
    is not a known schema kind. Returns ``None`` on success.
    """
    _validator(kind).validate(obj)


def is_valid(kind: str, obj: Any) -> bool:
    """Return True if ``obj`` validates against the schema for ``kind``."""
    return _validator(kind).is_valid(obj)
