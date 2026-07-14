"""Live P1+P2 over real TTS (``-m gpu``, opt-in; skipped by the default offline run).

Runs the first 10 pg35 pages through the actual text-transform-service on the LAN and
asserts only schema/shape (never LLM content, per CLAUDE.md). Prints a cast summary to paste
into CYCLE-LOG. Requires ``TTS_URL`` to point at a reachable TTS T5 instance.

    cd server && TTS_URL=http://<5070-host>:8712 uv run pytest -m gpu test_cast_live.py -s
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from scriptorium.bake import job as jobmod
from scriptorium.bake.job import Job, JobState
from scriptorium.bake.runner import Runner
from scriptorium.config import load_config
from scriptorium.ingest.base import KIND_TEXT, SourceSpec, load
from scriptorium.paginate.engine import paginate

pytestmark = pytest.mark.gpu

_SOURCE = Path(__file__).parent / "fixtures" / "sources" / "pg35.txt"
_N_PAGES = 10


@pytest.mark.skipif(not os.environ.get("TTS_URL"), reason="TTS_URL not set")
def test_live_cast_pipeline(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SCRIPTORIUM_DATA", str(tmp_path))
    cfg = load_config()

    book = paginate(load(SourceSpec(kind=KIND_TEXT, path=_SOURCE, filename="pg35.txt")))
    pages_dir = cfg.work_dir / "live" / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    for page in book.pages[:_N_PAGES]:
        (pages_dir / f"{page['id']}.json").write_text(
            json.dumps(page, ensure_ascii=False), encoding="utf-8"
        )

    Job(id="live", book_id="live", state=JobState.INGESTED, started=True).save(cfg)

    from scriptorium.app import BAKE_PIPELINE  # the registered real pipeline

    runner = Runner(cfg, BAKE_PIPELINE)
    for _ in range(60):
        asyncio.run(runner.tick())
        job = jobmod.load(cfg, "live")
        if job.state in {JobState.CAST_DONE, JobState.FAILED}:
            break

    job = jobmod.load(cfg, "live")
    assert job.state == JobState.CAST_DONE, f"ended in {job.state}, failed={job.failed_units}"

    from scriptorium import schemas

    doc = json.loads((cfg.work_dir / "live" / "cast.json").read_text(encoding="utf-8"))
    schemas.validate("cast", doc)
    majors = [c for c in doc["characters"] if c["major"]]
    assert majors, "expected at least one major character"

    print("\n=== live cast.json summary (first 10 pg35 pages) ===")
    for c in doc["characters"]:
        tag = "MAJOR" if c["major"] else "minor"
        print(f"  [{tag}] {c['slug']:<20} pages={len(c['mention_pages'])} "
              f"aliases={c['aliases']}")
