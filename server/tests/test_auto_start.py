"""Auto-start opt-in (ADR-0020): ``AUTO_START`` marks a freshly-ingested job ``started`` so the
runner advances it without a Start click — the first half of a full unattended run (pairs with
``AUTO_APPROVE``).

Assertions are state/flag only. Plain ``TestClient(app)`` (no context manager) so the background
runner never starts — matching ``test_admin_books.py``; we check the persisted ``started`` flag, not
a live advance.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from scriptorium.app import app
from scriptorium.config import load_config

MD = (Path(__file__).parent / "fixtures" / "sources" / "frontmatter.md").read_text("utf-8")


def _client(monkeypatch, tmp_path, *, auto_start: bool) -> TestClient:
    monkeypatch.setenv("SCRIPTORIUM_DATA", str(tmp_path))
    if auto_start:
        monkeypatch.setenv("AUTO_START", "1")
    else:
        monkeypatch.delenv("AUTO_START", raising=False)
    return TestClient(app)


def _create(client: TestClient) -> str:
    resp = client.post("/api/admin/books", json={
        "source": {"kind": "markdown", "text": MD, "filename": "frontmatter.md"},
        "bake": {"style_id": "engraving", "density_preset": "classic", "portraits_enabled": True},
    })
    assert resp.status_code == 200, resp.text
    return resp.json()["book_id"]


def test_env_flag_sets_config(monkeypatch) -> None:
    monkeypatch.setenv("AUTO_START", "1")
    assert load_config().auto_start is True
    monkeypatch.delenv("AUTO_START", raising=False)
    assert load_config().auto_start is False


def test_auto_start_marks_new_book_started(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path, auto_start=True)
    body = client.get(f"/api/admin/books/{_create(client)}").json()
    assert body["state"] == "ingested"  # still ingests + paginates first
    assert body["started"] is True      # …but is already started, so the runner will advance it


def test_default_leaves_new_book_unstarted(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path, auto_start=False)
    body = client.get(f"/api/admin/books/{_create(client)}").json()
    assert body["state"] == "ingested"
    assert body["started"] is False     # default: waits for the human Start (chapter-edit window)
