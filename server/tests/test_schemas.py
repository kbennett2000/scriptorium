"""Schema validation tests: every kind has a valid sample that passes and an
invalid sample that fails (BUILD-PLAN S1 acceptance)."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from scriptorium.schemas import SCHEMA_KINDS, is_valid, validate

FIXTURES = Path(__file__).parent / "fixtures" / "schemas"


def _load(name: str) -> object:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("kind", SCHEMA_KINDS)
def test_valid_sample_passes(kind: str) -> None:
    obj = _load(f"{kind}.valid.json")
    validate(kind, obj)  # must not raise
    assert is_valid(kind, obj)


@pytest.mark.parametrize("kind", SCHEMA_KINDS)
def test_invalid_sample_fails(kind: str) -> None:
    obj = _load(f"{kind}.invalid.json")
    assert not is_valid(kind, obj)
    with pytest.raises(jsonschema.ValidationError):
        validate(kind, obj)


def test_all_kinds_have_a_schema_file() -> None:
    for kind in SCHEMA_KINDS:
        assert (FIXTURES / f"{kind}.valid.json").exists()
        assert (FIXTURES / f"{kind}.invalid.json").exists()


def test_unknown_kind_raises() -> None:
    with pytest.raises(ValueError):
        validate("nonsense", {})


def test_seed_styles_json_validates() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    seed = json.loads((repo_root / "data" / "styles.json").read_text(encoding="utf-8"))
    validate("styles", seed)
