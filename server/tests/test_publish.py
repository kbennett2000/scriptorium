"""P8 publish + post-publish regen (DESIGN §4.2–4.4, §10) — the S10b acceptance boxes.

Builds a real published bundle via the shared offline harness (:mod:`_pipeline_build`), then
exercises the invariants:

- **Integrity guard** (§4.4): once published, a re-publish whose page bytes differ is refused.
- **Additive post-publish regen** (§10): a per-plate regen writes a new ``-rN`` variant beside the
  untouched original, bumps the revision, rebuilds the manifest, and the bundle still verifies.
- **Idempotency**: re-publishing the same work tree rewrites the bundle without corrupting it.

Image content is never asserted (CLAUDE.md) — only presence, sizes-via-schema, and cross-refs.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from verify_bundle import verify_bundle  # tools/ on path via conftest

import _pipeline_build as pb  # sibling harness (tests/ on path via conftest)
from scriptorium.app import app
from scriptorium.bake import job as jobmod
from scriptorium.bake.job import JobState
from scriptorium.bake.phases.base import PipelineBug
from scriptorium.bake.phases.p8_publish import Publish, publish_bundle
from scriptorium.render.imagegen import FakeImagegen


def _published(tmp_path):
    """Build a published bundle and return (cfg, book_id, library_dir)."""
    cfg = pb.make_cfg(tmp_path)
    book_id = pb.build_to_published(cfg, freeze=False)
    return cfg, book_id, cfg.library_dir / book_id


def test_integrity_guard_refuses_a_changed_page(tmp_path) -> None:
    cfg, book_id, library = _published(tmp_path)
    job = jobmod.load(cfg, book_id)

    # Mutate one work page's bytes, then attempt a re-publish: it must be refused (§4.4).
    page = next((cfg.work_dir / book_id / "pages").glob("*.json"))
    original = page.read_bytes()
    page.write_bytes(original[:-1] + b" ")  # a different byte sequence, still valid-ish JSON tail

    with pytest.raises(PipelineBug, match="integrity violation"):
        publish_bundle(cfg, job)

    # The published page is untouched.
    published_page = library / "pages" / page.name
    assert published_page.read_bytes() == original
    assert verify_bundle(library) == []


def test_republish_same_tree_is_idempotent(tmp_path) -> None:
    cfg, book_id, library = _published(tmp_path)
    job = jobmod.load(cfg, book_id)

    manifest_before = json.loads((library / "manifest.json").read_text("utf-8"))
    # A second publish of the unchanged work tree bumps the revision but keeps the bundle valid, and
    # the reader-facing derivative bytes are unchanged (same content, sidecar/deterministic pixels).
    webp = library / "images" / "web" / "cover.webp"
    web_before = webp.read_bytes()
    publish_bundle(cfg, job)
    manifest_after = json.loads((library / "manifest.json").read_text("utf-8"))

    assert manifest_after["revision"] == manifest_before["revision"] + 1
    assert webp.read_bytes() == web_before
    assert verify_bundle(library) == []


def test_manifest_content_fingerprint_is_derived_from_the_file_list(tmp_path) -> None:
    """The manifest exposes a 64-hex ``content_fingerprint`` that is exactly the hash of its own
    ``files`` list — so a reader comparing the field tracks the bundle's bytes."""
    from scriptorium.bake.phases.p8_publish import _content_fingerprint

    _cfg, _book_id, library = _published(tmp_path)
    m = json.loads((library / "manifest.json").read_text("utf-8"))
    fp = m["content_fingerprint"]
    assert isinstance(fp, str) and len(fp) == 64 and all(c in "0123456789abcdef" for c in fp)
    assert fp == _content_fingerprint(m["files"])


def test_content_fingerprint_changes_with_content() -> None:
    """Different file content ⇒ different fingerprint, even at the same book_id/revision — the exact
    signal a reader needs to notice a deleted-and-re-made bundle (same identity, new content)."""
    from scriptorium.bake.phases.p8_publish import _content_fingerprint

    base = [
        {"path": "pages/0001.json", "sha256": "a" * 64, "bytes": 10},
        {"path": "pages/0002.json", "sha256": "b" * 64, "bytes": 20},
    ]
    same = [dict(base[1]), dict(base[0])]  # order must not matter (sorted internally)
    changed = [base[0], {"path": "pages/0002.json", "sha256": "c" * 64, "bytes": 20}]

    assert _content_fingerprint(base) == _content_fingerprint(same)
    assert _content_fingerprint(base) != _content_fingerprint(changed)


def test_post_publish_regen_is_additive_and_verifies(tmp_path) -> None:
    cfg, book_id, library = _published(tmp_path)
    job = jobmod.load(cfg, book_id)

    selection = json.loads((library / "selection.json").read_text("utf-8"))
    page_id = selection["plates"][0]["page_id"]
    original = (library / "images" / "plates" / f"{page_id}.png").read_bytes()

    from scriptorium.bake.phases.p8_publish import regen_published_plate
    doc = asyncio.run(regen_published_plate(cfg, job, page_id, FakeImagegen(), seed=424242))

    # Revision bumped 1 → 2; a -r2 variant exists beside the untouched original.
    meta = json.loads((library / "meta.json").read_text("utf-8"))
    assert meta["revision"] == 2
    assert (library / "images" / "plates" / f"{page_id}-r2.png").is_file()
    assert (library / "images" / "web" / "plates" / f"{page_id}-r2.webp").is_file()
    assert (library / "images" / "thumbs" / "plates" / f"{page_id}-r2.webp").is_file()
    assert (library / "images" / "plates" / f"{page_id}.png").read_bytes() == original  # frozen
    assert doc["render"]["attempts"] == 2

    # Manifest picked up the new files, and the bundle still verifies (tolerates -rN variants).
    manifest = json.loads((library / "manifest.json").read_text("utf-8"))
    assert manifest["revision"] == 2
    assert any(f["path"].endswith(f"{page_id}-r2.png") for f in manifest["files"])
    assert verify_bundle(library) == []


def test_publish_phase_transitions_rendered_to_published(tmp_path) -> None:
    cfg, book_id, _ = _published(tmp_path)
    # The build already drove the real Publish phase to `published`.
    assert jobmod.load(cfg, book_id).state == JobState.PUBLISHED
    phase = Publish()
    assert phase.from_state == JobState.RENDERED and phase.to_state == JobState.PUBLISHED


def test_chosen_model_is_pinned_in_meta_provenance(tmp_path) -> None:
    # ADR-0030: a book's chosen base model overrides the service-reported imagegen tag in meta, so
    # re-renders (post-publish -rN, art-set re-rolls) can reproduce this book's exact model.
    from scriptorium.bake.phases.p8_publish import build_meta
    cfg, book_id, library = _published(tmp_path)
    job = jobmod.load(cfg, book_id)

    default = build_meta(cfg, job, library, revision=1)["bake"]["models"]["imagegen"]
    assert default == "unknown"  # no IMAGEGEN_URL in the offline harness → service-reported default

    job.bake_config["model"] = "chosen.safetensors"
    pinned = build_meta(cfg, job, library, revision=1)["bake"]["models"]["imagegen"]
    assert pinned == "chosen.safetensors"


def test_custom_style_text_is_pinned_in_meta(tmp_path) -> None:
    # ADR-0031: a book's free-text custom look is pinned in meta.custom_style so art-set re-rolls
    # and -rN regens reproduce it; a catalog style pins null.
    from scriptorium.bake.phases.p8_publish import build_meta
    cfg, book_id, library = _published(tmp_path)
    job = jobmod.load(cfg, book_id)

    assert build_meta(cfg, job, library, revision=1)["custom_style"] is None

    job.bake_config["style_id"] = "custom"
    job.bake_config["custom_style"] = "photorealistic"
    meta = build_meta(cfg, job, library, revision=1)
    assert meta["style_id"] == "custom" and meta["custom_style"] == "photorealistic"


@pytest.fixture
def published_client(monkeypatch, tmp_path):
    """A TestClient over a data dir that already holds a published bundle + its job."""
    cfg, book_id, _ = _published(tmp_path)
    monkeypatch.setenv("SCRIPTORIUM_DATA", str(tmp_path))
    monkeypatch.setattr(
        "scriptorium.bake.review_api._imagegen_client", lambda _cfg: FakeImagegen())
    return TestClient(app), book_id, cfg


def test_regen_endpoint_published_writes_r2(published_client) -> None:
    client, book_id, cfg = published_client
    library = cfg.library_dir / book_id
    page_id = json.loads((library / "selection.json").read_text("utf-8"))["plates"][0]["page_id"]

    r = client.post(f"/api/admin/books/{book_id}/plates/{page_id}/regen")
    assert r.status_code == 200, r.text
    assert r.json()["render"]["attempts"] == 2
    assert (library / "images" / "plates" / f"{page_id}-r2.png").is_file()
    assert json.loads((library / "meta.json").read_text("utf-8"))["revision"] == 2
