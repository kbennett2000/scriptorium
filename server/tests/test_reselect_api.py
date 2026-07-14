"""Reselect endpoint (DESIGN §8, §11.1) — density re-turn + P5 re-queue.

Pre-publish, with nothing rendered and no manual plates, the §8 merge reduces to "the merged plate
set is exactly the fresh selection" (never-rendered non-chosen plates are dropped), so the endpoint
output can be pinned against :func:`select` directly. Also checks the state re-queue to ``selected``
and the past-approval guard.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scriptorium.app import app
from scriptorium.bake import job as jobmod
from scriptorium.bake.job import Job, JobState
from scriptorium.config import load_config
from scriptorium.selection.engine import PRESETS, PageScore, select

_N = 12  # two chapters of six pages → past the tiny-work threshold, so presets bite.


@pytest.fixture
def client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setenv("SCRIPTORIUM_DATA", str(tmp_path))
    return TestClient(app)


def _page(seq: int, chapter: int, salience: float, scene_changed: bool) -> dict:
    pid = f"{seq:04d}"
    return {"id": pid, "seq": seq, "chapter": chapter, "text": f"page {pid}", "word_count": 2,
            "ledger": {"location": "x", "time_of_day": "day", "atmosphere": "y",
                       "present": [], "scene_changed": scene_changed, "visual_salience": salience,
                       "best_visual_beat": "a beat", "carry_notes": ""}}


def _pages() -> list[dict]:
    # Uniformly high salience, no scene changes, two chapters (openers 0001/0007): only the fill
    # step differs across presets, so lavish (max_gap 3) is strictly denser than classic/sparse.
    pages = []
    for seq in range(1, _N + 1):
        pages.append(_page(seq, 1 if seq <= 6 else 2, 0.9, False))
    return pages


def _scores(pages) -> list[PageScore]:
    return [PageScore(seq=p["seq"], page_id=p["id"], chapter=p["chapter"],
                      scene_changed=p["ledger"]["scene_changed"],
                      visual_salience=p["ledger"]["visual_salience"]) for p in pages]


def _structure() -> dict:
    return {"chapters": [
        {"index": 1, "title": "I", "page_ids": [f"{s:04d}" for s in range(1, 7)]},
        {"index": 2, "title": "II", "page_ids": [f"{s:04d}" for s in range(7, 13)]},
    ]}


def _fresh_ids(pages, preset: str) -> set[str]:
    return {c.page_id for c in select(_scores(pages), _structure(), PRESETS[preset])}


def _seed(tmp_path: Path, *, preset: str, state: str) -> str:
    book_id = "resel"
    cfg = load_config()
    work = cfg.work_dir / book_id
    (work / "pages").mkdir(parents=True, exist_ok=True)
    pages = _pages()
    for p in pages:
        (work / "pages" / f"{p['id']}.json").write_text(json.dumps(p), encoding="utf-8")
    (work / "structure.json").write_text(json.dumps(_structure()), encoding="utf-8")
    fresh = select(_scores(pages), _structure(), PRESETS[preset])
    (work / "selection.json").write_text(json.dumps({
        "preset": preset, "params": PRESETS[preset].as_dict(),
        "plates": [{"page_id": c.page_id, "reason": c.reason, "salience": c.salience,
                    "status": "selected", "added_in_revision": 1} for c in fresh],
    }), encoding="utf-8")
    Job(id=book_id, book_id=book_id, state=state, started=True).save(cfg)
    return book_id


def test_reselect_denser_adds_plates_and_requeues(client, tmp_path) -> None:
    book_id = _seed(tmp_path, preset="classic", state=JobState.PROMPTS_DRAFT)
    r = client.post(f"/api/admin/books/{book_id}/reselect", json={"density_preset": "lavish"})
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["preset"] == "lavish"
    ids = {p["page_id"] for p in doc["plates"]}
    assert ids == _fresh_ids(_pages(), "lavish")
    assert len(ids) > len(_fresh_ids(_pages(), "classic"))  # denser preset → more plates

    # Re-queued to `selected` so the runner re-runs P5 for the newcomers.
    assert jobmod.load(load_config(), book_id).state == JobState.SELECTED


def test_reselect_sparser_drops_never_rendered_plates(client, tmp_path) -> None:
    book_id = _seed(tmp_path, preset="lavish", state=JobState.PROMPTS_DRAFT)
    seeded = len(_fresh_ids(_pages(), "lavish"))
    r = client.post(f"/api/admin/books/{book_id}/reselect", json={"density_preset": "sparse"})
    assert r.status_code == 200
    ids = {p["page_id"] for p in r.json()["plates"]}
    assert ids == _fresh_ids(_pages(), "sparse")
    assert len(ids) < seeded  # never-rendered non-chosen plates were dropped


def test_reselect_guarded_past_approval(client, tmp_path) -> None:
    book_id = _seed(tmp_path, preset="classic", state=JobState.APPROVED)
    assert client.post(f"/api/admin/books/{book_id}/reselect",
                       json={"density_preset": "lavish"}).status_code == 409


def test_reselect_unknown_preset(client, tmp_path) -> None:
    book_id = _seed(tmp_path, preset="classic", state=JobState.PROMPTS_DRAFT)
    assert client.post(f"/api/admin/books/{book_id}/reselect",
                       json={"density_preset": "epic"}).status_code == 400
