"""Live P3 over real TTS (``-m gpu``, opt-in; skipped by the default offline run).

Threads ``scene-update`` over the first 8 pg35 pages through the actual text-transform-service
on the LAN and asserts only schema/shape (never LLM content, per CLAUDE.md). Prints a per-page
ledger summary to paste into CYCLE-LOG. Requires ``TTS_URL`` to point at a reachable TTS T5.

    cd server && TTS_URL=http://<5070-host>:8712 uv run pytest -m gpu test_ledger_live.py -s

The job is seeded directly at ``cast_done`` with a minimal ``cast.json`` so only P3 runs (the
full cast pipeline is exercised by ``test_cast_live.py``).
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from scriptorium.bake import job as jobmod
from scriptorium.bake.job import Job, JobState
from scriptorium.bake.phases.p3_ledger import LedgerEnter, LedgerScenes
from scriptorium.bake.runner import Runner
from scriptorium.config import load_config
from scriptorium.ingest.base import KIND_TEXT, SourceSpec, load
from scriptorium.paginate.engine import paginate

pytestmark = pytest.mark.gpu

_SOURCE = Path(__file__).parent / "fixtures" / "sources" / "pg35.txt"
_N_PAGES = 8


@pytest.mark.skipif(not os.environ.get("TTS_URL"), reason="TTS_URL not set")
def test_live_ledger_pipeline(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SCRIPTORIUM_DATA", str(tmp_path))
    cfg = load_config()

    book = paginate(load(SourceSpec(kind=KIND_TEXT, path=_SOURCE, filename="pg35.txt")))
    root = cfg.work_dir / "live"
    pages_dir = root / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    for page in book.pages[:_N_PAGES]:
        (pages_dir / f"{page['id']}.json").write_text(
            json.dumps(page, ensure_ascii=False), encoding="utf-8"
        )
    (root / "cast.json").write_text(
        json.dumps({"characters": [{"name": "the Time Traveller"}, {"name": "Weena"}]}),
        encoding="utf-8",
    )

    Job(id="live", book_id="live", state=JobState.CAST_DONE, started=True).save(cfg)

    runner = Runner(cfg, [LedgerEnter(), LedgerScenes()])
    for _ in range(80):
        asyncio.run(runner.tick())
        job = jobmod.load(cfg, "live")
        if job.state in {JobState.LEDGER_DONE, JobState.FAILED}:
            break

    job = jobmod.load(cfg, "live")
    assert job.state == JobState.LEDGER_DONE, f"ended in {job.state}, failed={job.failed_units}"

    from scriptorium import schemas

    print("\n=== live scene ledgers (first 8 pg35 pages) ===")
    for page_file in sorted(pages_dir.glob("*.json")):
        page = json.loads(page_file.read_text(encoding="utf-8"))
        schemas.validate("page", page)
        led = page["ledger"]
        print(f"  {page['id']}  changed={str(led['scene_changed']):<5} "
              f"sal={led['visual_salience']:.2f}  {led['location'][:48]}")
