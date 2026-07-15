"""Permanent book deletion (owner-initiated) — purge_book + the admin DELETE endpoint.

A delete removes EVERYTHING a book owns: its published bundle, bake work tree, job records (book +
set jobs), every profile's private picture sets, and every profile's sync data (annotations,
positions, backups). Nothing belonging to *other* books is touched. Deletion is refused while the
book is actively rendering.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scriptorium.app import app
from scriptorium.bake import job as jobmod
from scriptorium.bake.job import Job, JobState
from scriptorium.config import Config
from scriptorium.library.purge import purge_book

BOOK = "usr-abc123def456"
OTHER = "pg-35"


def _seed_everything(tmp_path: Path, book: str = BOOK) -> list[Path]:
    """Create one file in every place a book leaves data; return those paths."""
    paths = [
        tmp_path / "library" / book / "manifest.json",
        tmp_path / "work" / book / "structure.json",
        tmp_path / "jobs" / f"{book}.json",
        tmp_path / "jobs" / f"{book}#set-0123456789ab.json",
        tmp_path / "artsets" / "kris" / book / "set-0123456789ab" / "set.json",
        tmp_path / "artsets" / "amy" / book / "set-ffffffffffff" / "set.json",
        tmp_path / "sync" / "annotations" / "kris" / f"{book}.json",
        tmp_path / "sync" / "positions" / "amy" / f"{book}.json",
        tmp_path / "sync" / "annotations-backups" / "kris" / book / "2026.json",
    ]
    for p in paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}", encoding="utf-8")
    return paths


def _cfg(tmp_path) -> Config:
    return Config(
        data_dir=tmp_path, port=8720, tts_url=None, imagegen_url=None, gpu_mac=None,
        gpu_wol_enabled=False, runner_tick_s=1, shared_dir=Path("shared"),
    )


def test_purge_book_removes_every_footprint_and_spares_other_books(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    mine = _seed_everything(tmp_path, BOOK)
    theirs = _seed_everything(tmp_path, OTHER)

    removed = purge_book(cfg, BOOK)

    assert all(not p.exists() for p in mine), "some of the book's data survived"
    assert all(p.exists() for p in theirs), "another book's data was deleted"
    # The report lists each removed path, data-dir-relative.
    assert f"library/{BOOK}" in removed
    assert f"jobs/{BOOK}#set-0123456789ab.json" in removed
    assert any(r == f"artsets/kris/{BOOK}" for r in removed)


def test_purge_book_rejects_a_malformed_id(tmp_path) -> None:
    with pytest.raises(ValueError, match="bad book id"):
        purge_book(_cfg(tmp_path), "../etc")


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SCRIPTORIUM_DATA", str(tmp_path))
    return TestClient(app)


def test_delete_endpoint_removes_the_book(client, tmp_path) -> None:
    _seed_everything(tmp_path, BOOK)
    # A real (published) job record — the endpoint loads it to check the book isn't mid-render.
    Job(id=BOOK, book_id=BOOK, state=JobState.PUBLISHED).save(_cfg(tmp_path))
    resp = client.delete(f"/api/admin/books/{BOOK}")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == BOOK
    assert not (tmp_path / "library" / BOOK).exists()
    assert not (tmp_path / "artsets" / "kris" / BOOK).exists()


def test_delete_unknown_book_is_404(client) -> None:
    assert client.delete("/api/admin/books/usr-000000000000").status_code == 404


def test_delete_refused_while_rendering(client, tmp_path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    (tmp_path / "library" / BOOK).mkdir(parents=True)
    # A book whose job is on the GPU (rendering) must not be yanked out from under the worker.
    Job(id=BOOK, book_id=BOOK, state=JobState.RENDERING).save(cfg)
    monkeypatch.setenv("SCRIPTORIUM_DATA", str(tmp_path))
    resp = client.delete(f"/api/admin/books/{BOOK}")
    assert resp.status_code == 409
    assert (tmp_path / "library" / BOOK).exists()  # nothing deleted
    assert jobmod.load(cfg, BOOK) is not None
