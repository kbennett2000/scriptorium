"""Admin book/job endpoints (DESIGN §11.1, the S4 groups).

``POST /api/admin/books`` runs P0 inline and must leave schema-valid pages + structure in
``work/{id}``; the rest cover list/detail, the pre-P1 chapter-edit 409 guard, and the
start/pause/resume controls. Plain ``TestClient(app)`` (no context manager) is used so the
background runner never starts — matching ``test_health.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scriptorium.app import app
from scriptorium.schemas import validate

MD = (Path(__file__).parent / "fixtures" / "sources" / "frontmatter.md").read_text(
    encoding="utf-8"
)


@pytest.fixture
def client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setenv("SCRIPTORIUM_DATA", str(tmp_path))
    return TestClient(app)


def _create(client: TestClient) -> dict:
    resp = client.post(
        "/api/admin/books",
        json={
            "source": {"kind": "markdown", "text": MD, "filename": "frontmatter.md"},
            "bake": {
                "style_id": "engraving",
                "density_preset": "classic",
                "portraits_enabled": True,
            },
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_models_endpoint_degrades_when_imagegen_unset(client) -> None:
    # ADR-0030: GET /api/admin/models never 500s; with no IMAGEGEN_URL it reports an empty,
    # unreachable list so the picker falls back to the service default.
    resp = client.get("/api/admin/models")
    assert resp.status_code == 200
    assert resp.json() == {"models": [], "default": None, "reachable": False}


def test_create_book_persists_chosen_model(client) -> None:
    # ADR-0030: a chosen base model round-trips into the job's bake_config.
    resp = client.post(
        "/api/admin/books",
        json={
            "source": {"kind": "markdown", "text": MD, "filename": "frontmatter.md"},
            "bake": {"style_id": "engraving", "model": "dreamshaper.safetensors"},
        },
    )
    assert resp.status_code == 200, resp.text
    book = client.get(f"/api/admin/books/{resp.json()['book_id']}").json()
    assert book["bake_config"]["model"] == "dreamshaper.safetensors"


def test_create_book_runs_p0_and_persists_schema_valid_work(client, tmp_path) -> None:
    body = _create(client)
    assert body["book_id"].startswith("usr-")
    assert body["state"] == "ingested"
    assert body["warnings"] == []  # 3 detected chapters → no undetected warning

    work = tmp_path / "work" / body["book_id"]
    pages = sorted((work / "pages").glob("*.json"))
    assert pages, "P0 wrote no pages"
    for page_path in pages:
        validate("page", json.loads(page_path.read_text(encoding="utf-8")))
    validate("structure", json.loads((work / "structure.json").read_text("utf-8")))

    # Raw source archived for provenance (§5.1), and the job record exists.
    assert (work / "source" / "frontmatter.md").is_file()
    assert (tmp_path / "jobs" / f"{body['book_id']}.json").is_file()


def test_list_and_detail_and_404(client) -> None:
    book_id = _create(client)["book_id"]

    listed = client.get("/api/admin/books").json()["books"]
    assert any(b["id"] == book_id for b in listed)

    detail = client.get(f"/api/admin/books/{book_id}").json()
    assert detail["state"] == "ingested"
    assert detail["warnings"] == []
    assert detail["failed_units"] == []
    assert detail["title"] == "The Lantern Keeper"

    assert client.get("/api/admin/books/usr-nope").status_code == 404


def test_put_chapters_repaginates_then_409_past_p0(client, tmp_path) -> None:
    book_id = _create(client)["book_id"]
    before = len(list((tmp_path / "work" / book_id / "pages").glob("*.json")))
    assert before == 3  # three short chapters → three pages

    resp = client.put(
        f"/api/admin/books/{book_id}/chapters",
        json={"chapters": [{"title": "All One", "paragraphs": ["A short line."]}]},
    )
    assert resp.status_code == 200, resp.text
    after = len(list((tmp_path / "work" / book_id / "pages").glob("*.json")))
    assert after == 1  # re-paginated to a single page; stale pages removed

    # Move off `ingested` → the pre-P1 guard now rejects edits.
    assert client.post(f"/api/admin/jobs/{book_id}/pause").status_code == 200
    guarded = client.put(
        f"/api/admin/books/{book_id}/chapters",
        json={"chapters": [{"title": "x", "paragraphs": ["y"]}]},
    )
    assert guarded.status_code == 409


def test_start_pause_resume(client) -> None:
    book_id = _create(client)["book_id"]

    started = client.post(f"/api/admin/jobs/{book_id}/start").json()
    assert started["started"] is True
    assert started["state"] == "ingested"

    paused = client.post(f"/api/admin/jobs/{book_id}/pause").json()
    assert paused["state"] == "paused"
    assert paused["prev_state"] == "ingested"

    resumed = client.post(f"/api/admin/jobs/{book_id}/resume").json()
    assert resumed["state"] == "ingested"
    assert resumed["prev_state"] is None

    # Idempotency guards: can't resume a non-paused job, can't pause twice.
    assert client.post(f"/api/admin/jobs/{book_id}/resume").status_code == 409
    assert client.post(f"/api/admin/jobs/{book_id}/pause").status_code == 200
    assert client.post(f"/api/admin/jobs/{book_id}/pause").status_code == 409

    assert client.post("/api/admin/jobs/usr-nope/start").status_code == 404
