"""Single-plate regen (DESIGN §11.1, §10) — the pre-publish re-render path (S10a).

Two levels: ``render_plate`` directly (a fresh seed changes pixels and bumps ``render.attempts``),
and the ``POST …/plates/{id}/regen`` endpoint (rendered book → 200 + provenance bump; published →
409; unknown plate → 404). The imagegen client is a :class:`FakeImagegen` (injected for the endpoint
via the ``_imagegen_client`` seam). Image content is never asserted — only that it changed.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scriptorium.app import app
from scriptorium.bake.job import Job, JobState
from scriptorium.bake.phases.p7_render import render_plate
from scriptorium.config import Config, load_config
from scriptorium.render.imagegen import FakeImagegen


def _cfg(tmp_path) -> Config:
    repo_shared = Path(__file__).resolve().parents[2] / "shared"
    return Config(
        data_dir=tmp_path, port=8720, tts_url=None, imagegen_url=None, gpu_mac=None,
        gpu_wol_enabled=False, runner_tick_s=1, shared_dir=repo_shared,
    )


def _seed_book(cfg: Config, *, state: str, book_id: str = "b", rendered: bool = False) -> Job:
    book = cfg.work_dir / book_id
    (book / "prompts").mkdir(parents=True, exist_ok=True)
    doc = {"page_id": "0001", "derived": {"prompt": "a lamplit workshop", "avoid": ["color"]},
           "edited_prompt": None, "final_subject_prompt": "a lamplit workshop"}
    if rendered:
        doc["wrapped_prompt"] = "wrapped"
        doc["negative_prompt"] = "neg"
        doc["render"] = {"at": "2026-07-13T00:00:00Z", "params_echo": {"seed": 1}, "attempts": 1}
    (book / "prompts" / "0001.json").write_text(json.dumps(doc), encoding="utf-8")
    (book / "selection.json").write_text(json.dumps({
        "preset": "classic",
        "params": {"min_gap": 2, "max_gap": 6, "salience_floor": 0.55,
                   "chapter_open": True, "scene_boundary": True},
        "plates": [{"page_id": "0001", "reason": "chapter_open", "salience": 0.8,
                    "status": "rendered" if rendered else "approved", "added_in_revision": 1}],
    }), encoding="utf-8")
    job = Job(id=book_id, book_id=book_id, state=state, started=True,
              bake_config={"style_id": "engraving"})
    job.save(cfg)
    return job


def test_render_plate_new_seed_changes_output_and_bumps_attempts(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    job = _seed_book(cfg, state=JobState.RENDERED)
    png = cfg.work_dir / "b" / "images" / "plates" / "0001.png"
    prompt_path = cfg.work_dir / "b" / "prompts" / "0001.json"

    asyncio.run(render_plate(cfg, job, "0001", FakeImagegen()))  # default seed
    first = png.read_bytes()
    assert json.loads(prompt_path.read_text("utf-8"))["render"]["attempts"] == 1

    asyncio.run(render_plate(cfg, job, "0001", FakeImagegen(), seed=987654))  # new seed
    assert png.read_bytes() != first
    doc = json.loads(prompt_path.read_text("utf-8"))
    assert doc["render"]["attempts"] == 2
    assert doc["render"]["params_echo"]["seed"] == 987654


@pytest.fixture
def client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setenv("SCRIPTORIUM_DATA", str(tmp_path))
    # Inject the fake imagegen client into the regen endpoint (no GPU/network).
    monkeypatch.setattr("scriptorium.bake.review_api._imagegen_client", lambda _cfg: FakeImagegen())
    return TestClient(app)


def test_regen_endpoint_rerenders_a_plate(client, monkeypatch, tmp_path) -> None:
    _seed_book(load_config(), state=JobState.RENDERED, rendered=True)
    r = client.post("/api/admin/books/b/plates/0001/regen")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render"]["attempts"] == 2  # seeded at 1 → bumped
    assert (tmp_path / "work" / "b" / "images" / "plates" / "0001.png").is_file()


def test_regen_endpoint_published_without_library_is_404(client) -> None:
    # A published job whose plate has no library bundle file → 404 (the additive -rN path needs the
    # published bundle; the happy -r2 case is exercised in test_publish.py).
    _seed_book(load_config(), state=JobState.PUBLISHED, rendered=True)
    r = client.post("/api/admin/books/b/plates/0001/regen")
    assert r.status_code == 404
    assert "no published plate" in r.json()["detail"]


def test_regen_endpoint_404_for_unknown_plate(client) -> None:
    _seed_book(load_config(), state=JobState.RENDERED, rendered=True)
    r = client.post("/api/admin/books/b/plates/9999/regen")
    assert r.status_code == 404
