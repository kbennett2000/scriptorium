"""Library + checkout API (DESIGN §11.1) — the S11 acceptance boxes.

Seeds the committed fixture bundle into a tmp ``library/`` and exercises the three endpoints:
listing shape, manifest passthrough, path-traversal guard, the sha256 ETag / 304 flow, and the
**scripted-client checkout contract** (fetch manifest + every resolved reader-required file,
verify each hash). A final test drives a real ``-rN`` regen and asserts the resolved fetch set
carries exactly one current image per plate.

Image/LLM content is never asserted (CLAUDE.md) — only presence, hashes, sizes, and cross-refs.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from verify_bundle import verify_bundle  # tools/ on path via conftest

import _pipeline_build as pb  # sibling harness (tests/ on path via conftest)
from scriptorium.app import app
from scriptorium.bake import job as jobmod
from scriptorium.library.checkout import resolve_reader_files, resolved_total_bytes
from scriptorium.render.imagegen import FakeImagegen

_FIXTURE_BUNDLE = Path(__file__).parent / "fixtures" / "bundle"


def _seed_bundle(tmp_path: Path) -> str:
    """Copy the committed fixture bundle into ``tmp_path/library/{id}``; return the book id."""
    book_id = json.loads((_FIXTURE_BUNDLE / "manifest.json").read_text())["book_id"]
    shutil.copytree(_FIXTURE_BUNDLE, tmp_path / "library" / book_id)
    return book_id


@pytest.fixture
def seeded(monkeypatch, tmp_path) -> tuple[TestClient, str]:
    monkeypatch.setenv("SCRIPTORIUM_DATA", str(tmp_path))
    book_id = _seed_bundle(tmp_path)
    return TestClient(app), book_id


def test_library_listing_shape(seeded) -> None:
    client, book_id = seeded
    r = client.get("/api/library")
    assert r.status_code == 200
    books = r.json()
    assert len(books) == 1
    book = books[0]
    assert set(book) == {
        "id", "title", "author", "cover_thumb_url", "revision", "total_bytes_reader",
    }
    assert book["id"] == book_id
    assert book["revision"] == 1
    assert book["total_bytes_reader"] == 41812  # the fixture's resolved reader set (no variants)
    assert book["cover_thumb_url"] == f"/api/library/{book_id}/files/images/thumbs/cover.webp"


def test_listing_skips_incomplete_dirs(seeded, tmp_path) -> None:
    client, book_id = seeded
    (tmp_path / "library" / "junk-dir").mkdir()  # no manifest → skipped, not fatal
    (tmp_path / "library" / "loose.txt").write_text("x")  # not a dir → skipped
    r = client.get("/api/library")
    assert [b["id"] for b in r.json()] == [book_id]


def test_manifest_verbatim(seeded) -> None:
    client, book_id = seeded
    r = client.get(f"/api/library/{book_id}/manifest")
    assert r.status_code == 200
    assert r.json() == json.loads((_FIXTURE_BUNDLE / "manifest.json").read_text())
    assert client.get("/api/library/pg-99999/manifest").status_code == 404


def test_file_serving_content_types(seeded) -> None:
    client, book_id = seeded
    cases = {
        "meta.json": "application/json",
        "images/web/cover.webp": "image/webp",
        "images/plates/0001.png": "image/png",
    }
    for rel, ctype in cases.items():
        r = client.get(f"/api/library/{book_id}/files/{rel}")
        assert r.status_code == 200, rel
        assert r.headers["content-type"].split(";")[0] == ctype
    assert client.get(f"/api/library/{book_id}/files/pages/9999.json").status_code == 404


@pytest.mark.parametrize("evil", [
    "%2e%2e%2f%2e%2e%2fwork%2fsecret.json",       # ../../work/secret.json (encoded)
    "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd",    # climb out of data_dir entirely
    "images%2f%2e%2e%2f%2e%2e%2f%2e%2e%2fmeta.json",
])
def test_path_traversal_rejected(seeded, tmp_path, evil) -> None:
    client, book_id = seeded
    # Plant a secret in work/ to prove it is never reachable through the library route.
    (tmp_path / "work").mkdir(exist_ok=True)
    (tmp_path / "work" / "secret.json").write_text('{"leak": true}')
    r = client.get(f"/api/library/{book_id}/files/{evil}")
    assert r.status_code == 400, r.text
    assert "leak" not in r.text


def test_etag_and_304_flow(seeded) -> None:
    client, book_id = seeded
    url = f"/api/library/{book_id}/files/images/web/cover.webp"
    r1 = client.get(url)
    assert r1.status_code == 200
    etag = r1.headers["etag"]
    expected = hashlib.sha256((_FIXTURE_BUNDLE / "images/web/cover.webp").read_bytes()).hexdigest()
    assert etag == f'"{expected}"'

    r2 = client.get(url, headers={"If-None-Match": etag})
    assert r2.status_code == 304
    assert r2.content == b""

    r3 = client.get(url, headers={"If-None-Match": '"deadbeef"'})
    assert r3.status_code == 200


def test_scripted_client_checkout_contract(seeded) -> None:
    """The checkout in miniature: fetch manifest, then every resolved reader-required file."""
    client, book_id = seeded
    manifest = client.get(f"/api/library/{book_id}/manifest").json()
    resolved = resolve_reader_files(manifest)

    downloaded = 0
    for entry in resolved:
        r = client.get(f"/api/library/{book_id}/files/{entry['path']}")
        assert r.status_code == 200, entry["path"]
        assert hashlib.sha256(r.content).hexdigest() == entry["sha256"], entry["path"]
        downloaded += len(r.content)

    listed = client.get("/api/library").json()[0]
    assert downloaded == resolved_total_bytes(manifest) == listed["total_bytes_reader"]


def test_rn_fetch_set_has_exactly_one_current_image(monkeypatch, tmp_path) -> None:
    """After a regen, the resolved fetch set holds one web + one thumb per plate — the -r2."""
    cfg = pb.make_cfg(tmp_path)
    book_id = pb.build_to_published(cfg, freeze=False)
    library = cfg.library_dir / book_id
    job = jobmod.load(cfg, book_id)

    page_id = json.loads((library / "selection.json").read_text())["plates"][0]["page_id"]
    asyncio.run(pb_regen(cfg, job, page_id))

    manifest = json.loads((library / "manifest.json").read_text())
    resolved = {e["path"] for e in resolve_reader_files(manifest)}

    web = f"images/web/plates/{page_id}"
    thumb = f"images/thumbs/plates/{page_id}"
    web_hits = {p for p in resolved if p.startswith(web)}
    thumb_hits = {p for p in resolved if p.startswith(thumb)}
    assert web_hits == {f"{web}-r2.webp"}     # exactly one, the current variant
    assert thumb_hits == {f"{thumb}-r2.webp"}
    # The superseded base + full-res are still on disk / in the manifest (additive, §4.4).
    assert any(f["path"] == f"{web}.webp" for f in manifest["files"])
    assert verify_bundle(library) == []


async def pb_regen(cfg, job, page_id):
    from scriptorium.bake.phases.p8_publish import regen_published_plate
    return await regen_published_plate(cfg, job, page_id, FakeImagegen(), seed=424242)
