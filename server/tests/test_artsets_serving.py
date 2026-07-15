"""Picture-set serving API (DESIGN §8, ADR-0014 Phase 3) — private offline download.

Mirrors ``library/api.py``: a set's ``manifest.json`` + individual image files are served with an
``ETag = sha256`` (from the manifest), ``If-None-Match`` → 304, path-traversal guarded, and rooted
at ``artsets/{user}/{book}/{set_id}/`` — never ``library/{book}``. Asserts shape/paths/verification
only, never image content (CLAUDE.md).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scriptorium import schemas
from scriptorium.app import app
from scriptorium.bake.phases.p8_publish import build_manifest

USER = "kris"
BOOK = "usr-abc123def456"
SET = "set-0123456789ab"


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SCRIPTORIUM_DATA", str(tmp_path))
    return TestClient(app)


def _seed_set(tmp_path: Path, *, user: str = USER, book: str = BOOK, set_id: str = SET) -> dict:
    """A ready set dir: a couple web/thumb images + a real ``build_manifest`` manifest.json."""
    set_dir = tmp_path / "artsets" / user / book / set_id
    files = {
        "images/web/cover.webp": b"cover-bytes",
        "images/web/plates/0001.webp": b"plate-bytes",
        "images/thumbs/cover.webp": b"thumb-bytes",
    }
    for rel, data in files.items():
        p = set_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    manifest = build_manifest(set_dir, book, 1)
    (set_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def test_serves_the_set_manifest(client, tmp_path) -> None:
    manifest = _seed_set(tmp_path)
    resp = client.get(f"/api/artsets/{USER}/{BOOK}/{SET}/manifest")
    assert resp.status_code == 200
    doc = resp.json()
    schemas.validate("manifest", doc)
    assert doc == manifest
    assert doc["book_id"] == BOOK  # a set manifest carries the parent book id


def test_serves_a_file_with_sha256_etag(client, tmp_path) -> None:
    _seed_set(tmp_path)
    resp = client.get(f"/api/artsets/{USER}/{BOOK}/{SET}/files/images/web/cover.webp")
    assert resp.status_code == 200
    assert resp.content == b"cover-bytes"
    assert resp.headers["content-type"] == "image/webp"
    assert resp.headers["etag"].strip('"') == hashlib.sha256(b"cover-bytes").hexdigest()


def test_if_none_match_short_circuits_to_304(client, tmp_path) -> None:
    _seed_set(tmp_path)
    url = f"/api/artsets/{USER}/{BOOK}/{SET}/files/images/web/cover.webp"
    etag = client.get(url).headers["etag"]
    resp = client.get(url, headers={"If-None-Match": etag})
    assert resp.status_code == 304
    assert resp.headers["etag"] == etag


def test_path_traversal_is_rejected(client, tmp_path) -> None:
    _seed_set(tmp_path)
    # A body-relative escape resolves outside the set dir → 400 (the same guard as library serving).
    resp = client.get(f"/api/artsets/{USER}/{BOOK}/{SET}/files/../../../../etc/passwd")
    assert resp.status_code in (400, 404)


def test_missing_file_is_404(client, tmp_path) -> None:
    _seed_set(tmp_path)
    resp = client.get(f"/api/artsets/{USER}/{BOOK}/{SET}/files/images/web/nope.webp")
    assert resp.status_code == 404


def test_unknown_set_is_404(client) -> None:
    resp = client.get(f"/api/artsets/{USER}/{BOOK}/set-ffffffffffff/manifest")
    assert resp.status_code == 404


@pytest.mark.parametrize("set_id", ["default", "set-XYZ", "not-a-set", ".."])
def test_malformed_or_default_set_id_is_rejected(client, tmp_path, set_id) -> None:
    _seed_set(tmp_path)
    # 'default' has no bytes here (served from the book bundle); malformed ids are guarded.
    assert client.get(f"/api/artsets/{USER}/{BOOK}/{set_id}/manifest").status_code in (400, 404)


def test_serving_never_touches_the_library(client, tmp_path) -> None:
    _seed_set(tmp_path)
    client.get(f"/api/artsets/{USER}/{BOOK}/{SET}/files/images/web/cover.webp")
    assert not (tmp_path / "library").exists()  # serving reads only artsets/
