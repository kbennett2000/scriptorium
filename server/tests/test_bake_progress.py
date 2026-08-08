"""Read-time bake-progress derivation (admin status poll).

``phase_progress`` counts on-disk artifacts vs the phase's unit universe; ``status_extras`` adds the
liveness fields. Pure/offline — seed a work dir and assert counts/flags; no HTTP, no GPU.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scriptorium.app import app
from scriptorium.bake.job import Job, JobState
from scriptorium.bake.progress import phase_progress, status_extras
from scriptorium.config import Config


def _cfg(tmp_path: Path) -> Config:
    return Config(
        data_dir=tmp_path, port=8720, tts_url=None, imagegen_url=None, gpu_mac=None,
        gpu_wol_enabled=False, runner_tick_s=1, shared_dir=tmp_path,
    )


def _seed(cfg: Config, book: str, rel: str, n: int, ext: str = "json") -> None:
    d = cfg.work_dir / book / rel
    d.mkdir(parents=True, exist_ok=True)
    for i in range(1, n + 1):
        (d / f"{i:04d}.{ext}").write_text("{}" if ext == "json" else "x", encoding="utf-8")


def _job(state: str, *, started: bool = True) -> Job:
    return Job(id="b", book_id="b", state=state, started=started)


def test_mentions_progress_counts_artifacts_vs_pages(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _seed(cfg, "b", "pages", 10)
    _seed(cfg, "b", "mentions", 4)
    got = phase_progress(_job(JobState.MENTIONS_RUNNING), cfg)
    assert got == {"units_done": 4, "units_total": 10}


def test_ledger_progress_counts_ledgers_vs_pages(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _seed(cfg, "b", "pages", 8)
    _seed(cfg, "b", "ledgers", 8)
    assert phase_progress(_job(JobState.LEDGER_RUNNING), cfg) == {"units_done": 8, "units_total": 8}


def test_render_progress_counts_web_plates_vs_prompts(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _seed(cfg, "b", "prompts", 5)
    _seed(cfg, "b", "images/web/plates", 2, ext="webp")
    assert phase_progress(_job(JobState.RENDERING), cfg) == {"units_done": 2, "units_total": 5}


def test_cast_progress_counts_canon_vs_majors(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    (cfg.work_dir / "b" / "cast").mkdir(parents=True)
    (cfg.work_dir / "b" / "cast" / "groups.json").write_text(
        json.dumps([{"major": True}, {"major": True}, {"major": False}]), encoding="utf-8"
    )
    _seed(cfg, "b", "cast/canon", 1)
    assert phase_progress(_job(JobState.CAST_RUNNING), cfg) == {"units_done": 1, "units_total": 2}


def test_done_is_clamped_to_total(tmp_path) -> None:
    # A transiently over-counted dir (e.g. a stray file) never pushes the bar past 100%.
    cfg = _cfg(tmp_path)
    _seed(cfg, "b", "pages", 3)
    _seed(cfg, "b", "mentions", 5)
    clamped = phase_progress(_job(JobState.MENTIONS_RUNNING), cfg)
    assert clamped == {"units_done": 3, "units_total": 3}


def test_resting_phase_has_no_countable_progress(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    none = {"units_done": None, "units_total": None}
    assert phase_progress(_job(JobState.IN_REVIEW), cfg) == none
    assert phase_progress(_job(JobState.SELECTED), cfg) == none


@pytest.mark.parametrize(
    "state,started,expected",
    [
        (JobState.MENTIONS_RUNNING, True, True),
        (JobState.INGESTED, True, True),      # started but not advancing → a stall is real
        (JobState.RENDERING, True, True),
        (JobState.MENTIONS_RUNNING, False, False),  # not started yet
        (JobState.IN_REVIEW, True, False),    # awaiting human approval, not a stall
        (JobState.PROMPTS_DRAFT, True, False),
        (JobState.WAITING_GPU, True, False),  # has its own banner
        (JobState.PUBLISHED, True, False),
    ],
)
def test_expecting_progress_flag(tmp_path, state, started, expected) -> None:
    extras = status_extras(_job(state, started=started), _cfg(tmp_path))
    assert extras["expecting_progress"] is expected
    assert "server_now" in extras and extras["seconds_since_activity"] >= 0.0
    assert "progress" in extras


def test_get_book_endpoint_includes_progress_fields(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SCRIPTORIUM_DATA", str(tmp_path))
    client = TestClient(app)
    md = (Path(__file__).parent / "fixtures" / "sources" / "frontmatter.md").read_text("utf-8")
    created = client.post("/api/admin/books", json={
        "source": {"kind": "markdown", "text": md, "filename": "frontmatter.md"},
        "bake": {"style_id": "engraving", "density_preset": "classic", "portraits_enabled": True},
    })
    assert created.status_code == 200, created.text
    book_id = created.json()["book_id"]

    body = client.get(f"/api/admin/books/{book_id}").json()
    # Additive fields present alongside the raw job record.
    assert set(body["progress"]) == {"units_done", "units_total"}
    assert "server_now" in body and "seconds_since_activity" in body
    assert body["expecting_progress"] is False  # freshly ingested, not started
    assert body["state"] == "ingested"  # existing field untouched
