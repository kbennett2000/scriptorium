"""Picture-sets API tests (DESIGN §8, ADR-0014) — Phase 1 read-only listing.

Every book has a synthetic ``default`` set for every profile; personal sets arrive in later
cycles. Covers the response shape (schema-valid), the default entry, and the ``{user}``/``{book}``
traversal guard (mirrors the sync API). Asserts shape only, never image content (CLAUDE.md).
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from scriptorium import schemas
from scriptorium.app import app


def _publish(tmp_path, book: str = "usr-abc123def456", style_id: str = "engraving") -> str:
    """Minimal published book (just meta.json) — enough for create/list/delete (no render here)."""
    lib = tmp_path / "library" / book
    lib.mkdir(parents=True, exist_ok=True)
    (lib / "meta.json").write_text(json.dumps({
        "book_id": book, "revision": 1, "title": "T", "author": "A", "style_id": style_id,
    }), encoding="utf-8")
    return book


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SCRIPTORIUM_DATA", str(tmp_path))
    return TestClient(app)


def test_lists_the_synthetic_default_set(client) -> None:
    resp = client.get("/api/artsets/kris/pg-35")
    assert resp.status_code == 200
    doc = resp.json()
    schemas.validate("artset-list", doc)  # the acceptance box
    assert doc["book_id"] == "pg-35"
    assert doc["user_id"] == "kris"
    assert doc["active_set_id"] == "default"
    assert [s["set_id"] for s in doc["sets"]] == ["default"]
    default = doc["sets"][0]
    assert default["kind"] == "default"
    assert default["status"] == "ready"
    assert default["label"]  # human-facing, non-empty


def test_lists_for_a_user_authored_book_id(client) -> None:
    resp = client.get("/api/artsets/amy/usr-4feb0ab87a05")
    assert resp.status_code == 200
    assert resp.json()["book_id"] == "usr-4feb0ab87a05"


@pytest.mark.parametrize("user", ["Kris", "has_underscore", "bad/slash", ".."])
def test_rejects_malformed_user_id(client, user) -> None:
    assert client.get(f"/api/artsets/{user}/pg-35").status_code in (400, 404)


@pytest.mark.parametrize("book", ["not-a-book", "usr-XYZ", "pg-", ".."])
def test_rejects_malformed_book_id(client, book) -> None:
    assert client.get(f"/api/artsets/kris/{book}").status_code in (400, 404)


def test_create_lists_and_delete_a_set(client, tmp_path) -> None:
    book = _publish(tmp_path)
    resp = client.post(f"/api/artsets/kris/{book}", json={"kind": "style", "style_id": "engraving"})
    assert resp.status_code == 200
    doc = resp.json()
    schemas.validate("artset", doc)
    set_id = doc["set_id"]
    assert doc["status"] == "generating" and doc["style_id"] == "engraving"
    # set.json written + the set-scoped job enqueued (distinct from the book's own job id).
    assert (tmp_path / "artsets" / "kris" / book / set_id / "set.json").is_file()
    assert (tmp_path / "jobs" / f"{book}#{set_id}.json").is_file()
    assert not (tmp_path / "jobs" / f"{book}.json").exists()

    listed = client.get(f"/api/artsets/kris/{book}").json()
    schemas.validate("artset-list", listed)
    assert [s["set_id"] for s in listed["sets"]] == ["default", set_id]

    deleted = client.delete(f"/api/artsets/kris/{book}/{set_id}")
    assert deleted.status_code == 200
    assert not (tmp_path / "artsets" / "kris" / book / set_id).exists()
    assert not (tmp_path / "jobs" / f"{book}#{set_id}.json").exists()
    back = client.get(f"/api/artsets/kris/{book}").json()
    assert [s["set_id"] for s in back["sets"]] == ["default"]


def test_reroll_defaults_to_the_books_style(client, tmp_path) -> None:
    book = _publish(tmp_path, style_id="engraving")
    resp = client.post(f"/api/artsets/kris/{book}", json={"kind": "reroll"})
    assert resp.status_code == 200
    assert resp.json()["style_id"] == "engraving"


def test_style_set_records_chosen_model(client, tmp_path) -> None:
    # ADR-0030: a chosen base model is stored on set.json and on the set's render job's bake_config.
    book = _publish(tmp_path)
    resp = client.post(f"/api/artsets/kris/{book}", json={
        "kind": "style", "style_id": "engraving", "model": "dreamshaper.safetensors"})
    assert resp.status_code == 200
    doc = resp.json()
    schemas.validate("artset", doc)
    assert doc["model"] == "dreamshaper.safetensors"
    job = json.loads((tmp_path / "jobs" / f"{book}#{doc['set_id']}.json").read_text("utf-8"))
    assert job["bake_config"]["model"] == "dreamshaper.safetensors"


def test_custom_style_set_records_free_text_look(client, tmp_path) -> None:
    # ADR-0031: a set may render in a free-text "custom" look; the text is stored on set.json and
    # the set's render job.
    book = _publish(tmp_path)
    resp = client.post(f"/api/artsets/kris/{book}", json={
        "kind": "style", "style_id": "custom", "custom_style": "photorealistic"})
    assert resp.status_code == 200, resp.text
    doc = resp.json()
    schemas.validate("artset", doc)
    assert doc["style_id"] == "custom" and doc["custom_style"] == "photorealistic"
    assert doc["label"] == "photorealistic"  # the look names the set
    job = json.loads((tmp_path / "jobs" / f"{book}#{doc['set_id']}.json").read_text("utf-8"))
    assert job["bake_config"]["custom_style"] == "photorealistic"


def test_reroll_reproduces_a_custom_books_look(client, tmp_path) -> None:
    # A re-roll of a custom-look book reproduces that look (from meta.custom_style).
    book = "usr-abc123def456"
    lib = tmp_path / "library" / book
    lib.mkdir(parents=True, exist_ok=True)
    (lib / "meta.json").write_text(json.dumps({
        "book_id": book, "revision": 1, "title": "T", "author": "A",
        "style_id": "custom", "custom_style": "photorealistic",
    }), encoding="utf-8")
    resp = client.post(f"/api/artsets/kris/{book}", json={"kind": "reroll"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["style_id"] == "custom"
    assert resp.json()["custom_style"] == "photorealistic"


def test_reroll_defaults_model_from_the_books_pinned_model(client, tmp_path) -> None:
    # A re-roll reproduces the book's own model, pinned at publish in meta.bake.models.imagegen.
    book = "usr-abc123def456"
    lib = tmp_path / "library" / book
    lib.mkdir(parents=True, exist_ok=True)
    (lib / "meta.json").write_text(json.dumps({
        "book_id": book, "revision": 1, "title": "T", "author": "A", "style_id": "engraving",
        "bake": {"models": {"imagegen": "chosen.safetensors"}},
    }), encoding="utf-8")
    resp = client.post(f"/api/artsets/kris/{book}", json={"kind": "reroll"})
    assert resp.status_code == 200
    assert resp.json()["model"] == "chosen.safetensors"


def test_create_unknown_style_is_400(client, tmp_path) -> None:
    book = _publish(tmp_path)
    resp = client.post(f"/api/artsets/kris/{book}", json={"kind": "style", "style_id": "nope"})
    assert resp.status_code == 400


def test_create_unpublished_book_is_404(client) -> None:
    resp = client.post(
        "/api/artsets/kris/usr-000000000000", json={"kind": "style", "style_id": "engraving"}
    )
    assert resp.status_code == 404


def test_delete_default_is_rejected(client, tmp_path) -> None:
    book = _publish(tmp_path)
    assert client.delete(f"/api/artsets/kris/{book}/default").status_code == 400
