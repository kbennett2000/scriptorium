"""Unit tests for the standalone bundle verifier (``tools/verify_bundle.py``, DESIGN §4.2–4.4).

The committed fixture bundle verifies clean; each deliberate corruption is caught with a pointed
error. The verifier is the S10b guard that a published ``library/{id}`` is reader-serviceable.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from verify_bundle import verify_bundle

_FIXTURE = Path(__file__).parent / "fixtures" / "bundle"


def _copy(tmp_path) -> Path:
    dst = tmp_path / "bundle"
    shutil.copytree(_FIXTURE, dst)
    return dst


def test_committed_fixture_bundle_verifies_clean(tmp_path) -> None:
    assert verify_bundle(_copy(tmp_path)) == []


def test_missing_manifest_is_reported(tmp_path) -> None:
    bundle = _copy(tmp_path)
    (bundle / "manifest.json").unlink()
    errors = verify_bundle(bundle)
    assert any("missing manifest.json" in e for e in errors)


def test_tampered_file_fails_hash_check(tmp_path) -> None:
    bundle = _copy(tmp_path)
    page = next((bundle / "pages").glob("*.json"))
    page.write_bytes(page.read_bytes() + b"\n")  # change bytes without touching the manifest
    errors = verify_bundle(bundle)
    assert any("sha256 mismatch" in e or "byte-count mismatch" in e for e in errors)


def test_missing_reader_required_file_is_reported(tmp_path) -> None:
    bundle = _copy(tmp_path)
    for webp in (bundle / "images" / "web").rglob("*.webp"):
        webp.unlink()  # remove every reader web derivative → the glob matches nothing
    errors = verify_bundle(bundle)
    assert any("reader_required glob matches no file" in e for e in errors) or any(
        "manifest lists missing file" in e for e in errors)


def test_dangling_selection_reference_is_reported(tmp_path) -> None:
    bundle = _copy(tmp_path)
    sel = json.loads((bundle / "selection.json").read_text("utf-8"))
    sel["plates"].append({"page_id": "9999", "reason": "manual", "salience": 0.5,
                          "status": "approved", "added_in_revision": 1})
    (bundle / "selection.json").write_text(json.dumps(sel), encoding="utf-8")
    errors = verify_bundle(bundle)
    assert any("9999" in e and "no page file" in e for e in errors)


def test_retired_plate_missing_files_is_reported(tmp_path) -> None:
    bundle = _copy(tmp_path)
    # A retired plate must keep its files (additive invariant, §4.4). Reference a real page but
    # provide no prompt/image → the verifier flags the gap.
    page_id = next((bundle / "pages").glob("*.json")).stem
    sel = json.loads((bundle / "selection.json").read_text("utf-8"))
    if not any(p["page_id"] == page_id for p in sel["plates"]):
        sel["plates"].append({"page_id": page_id, "reason": "fill", "salience": 0.5,
                              "status": "retired", "added_in_revision": 1})
        (bundle / "selection.json").write_text(json.dumps(sel), encoding="utf-8")
        errors = verify_bundle(bundle)
        assert any(page_id in e and ("missing prompt file" in e or "image trio" in e)
                   for e in errors)
    else:
        pytest.skip("selected page already has a plate; retired-gap case not constructible here")
