"""Validate the committed fixture bundle (DESIGN §4.2, BUILD-PLAN Cycle S3).

The bundle under ``fixtures/bundle/`` is R1's dev diet and S10's verify target. This
test is the guard that it stays a *valid* bundle: every JSON validates against its
schema, every manifest entry's hash+size matches the file on disk, and every
reader-required file is present. Regenerate with ``tools/make_fixture_bundle.py``.
"""

from __future__ import annotations

import hashlib
import json
from fnmatch import fnmatch
from pathlib import Path

import pytest

from scriptorium.schemas import validate

BUNDLE = Path(__file__).parent / "fixtures" / "bundle"


def _load(rel: str) -> object:
    return json.loads((BUNDLE / rel).read_text(encoding="utf-8"))


def _reader_match(rel_path: str, patterns: list[str]) -> bool:
    for pat in patterns:
        if pat.endswith("/**"):
            if rel_path.startswith(pat[:-2]):
                return True
        elif fnmatch(rel_path, pat):
            return True
    return False


def _kind_for(rel_path: str) -> str | None:
    if rel_path == "manifest.json":
        return None  # validated explicitly; not self-listed
    top = {"meta.json": "meta", "structure.json": "structure",
           "cast.json": "cast", "selection.json": "selection"}.get(rel_path)
    if top:
        return top
    if rel_path.startswith("pages/"):
        return "page"
    if rel_path.startswith("prompts/"):
        return "prompt"
    return None  # images: no JSON schema


def test_manifest_validates_and_hashes_match():
    manifest = _load("manifest.json")
    validate("manifest", manifest)
    listed = {f["path"] for f in manifest["files"]}
    assert "manifest.json" not in listed  # manifest never lists itself
    for entry in manifest["files"]:
        path = BUNDLE / entry["path"]
        assert path.is_file(), f"missing file {entry['path']}"
        data = path.read_bytes()
        assert len(data) == entry["bytes"], f"size mismatch {entry['path']}"
        assert hashlib.sha256(data).hexdigest() == entry["sha256"], entry["path"]


def test_manifest_lists_every_file_on_disk():
    manifest = _load("manifest.json")
    listed = {f["path"] for f in manifest["files"]}
    on_disk = {
        p.relative_to(BUNDLE).as_posix()
        for p in BUNDLE.rglob("*")
        if p.is_file() and p.name != "manifest.json"
    }
    assert listed == on_disk


def test_every_json_validates_against_its_schema():
    for path in sorted(BUNDLE.rglob("*.json")):
        rel = path.relative_to(BUNDLE).as_posix()
        if rel == "manifest.json":
            continue
        kind = _kind_for(rel)
        assert kind is not None, f"no schema kind mapped for {rel}"
        validate(kind, json.loads(path.read_text(encoding="utf-8")))


def test_reader_required_files_all_present():
    manifest = _load("manifest.json")
    patterns = manifest["reader_required"]
    matched = [f for f in manifest["files"] if _reader_match(f["path"], patterns)]
    assert matched, "reader_required matched nothing"
    for f in matched:
        assert (BUNDLE / f["path"]).is_file()
    # total_bytes_reader is the sum over exactly the reader-required set
    assert manifest["total_bytes_reader"] == sum(f["bytes"] for f in matched)
    # full-res plate PNGs are archival — never reader-required (DESIGN §4.3)
    assert not any(f["path"].startswith("images/plates/") for f in matched)


def test_cross_references_are_consistent():
    page_ids = {
        json.loads(p.read_text(encoding="utf-8"))["id"]
        for p in (BUNDLE / "pages").glob("*.json")
    }
    selection = _load("selection.json")
    for plate in selection["plates"]:
        assert plate["page_id"] in page_ids
        assert (BUNDLE / "prompts" / f"{plate['page_id']}.json").is_file()
        assert (BUNDLE / "images" / "plates" / f"{plate['page_id']}.png").is_file()
    cast = _load("cast.json")
    for character in cast["characters"]:
        for pid in character["mention_pages"]:
            assert pid in page_ids
        if character["portrait"] is not None:
            assert (BUNDLE / character["portrait"]).is_file()


@pytest.mark.parametrize("pseudo", ["cover.json", "portrait-wanderer.json"])
def test_pseudo_plate_prompts_present(pseudo):
    validate("prompt", _load(f"prompts/{pseudo}"))
