"""Live P5 over real TTS (``-m gpu``, opt-in; skipped by the default offline run).

Derives ``illustration-prompt`` prompts over a small real pg35 selected set through the actual
text-transform-service on the LAN, asserting only schema/shape (never LLM content, per CLAUDE.md).
Prints the derived prompts + the CPU-assembled cover/portrait strings to paste into CYCLE-LOG.
Requires ``TTS_URL`` to point at a reachable TTS T5.

    cd server && TTS_URL=http://<5070-host>:8712 uv run pytest -m gpu test_prompts_live.py -s

The job is seeded at ``selected`` with real pages, a small hand-built ledger + cast + selection,
so only P5 runs (the full pipeline live is exercised by ``test_cast_live.py``).
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from scriptorium import schemas
from scriptorium.bake import job as jobmod
from scriptorium.bake.job import Job, JobState
from scriptorium.bake.phases.p5_prompts import PromptsDerive, PromptsEnter
from scriptorium.bake.runner import Runner
from scriptorium.config import load_config
from scriptorium.ingest.base import KIND_TEXT, SourceSpec, load
from scriptorium.paginate.engine import paginate

pytestmark = pytest.mark.gpu

_SOURCE = Path(__file__).parent / "fixtures" / "sources" / "pg35.txt"
_N_PAGES = 3

_CAST = {"characters": [
    {"slug": "the-time-traveller", "name": "the Time Traveller", "aliases": ["the Traveller"],
     "mention_pages": ["0001", "0002", "0003"], "major": True,
     "visual_description": "a lean, pale-faced inventor with restless grey eyes, Victorian dress",
     "one_line": "The restless inventor of the machine.", "tags": ["inventor"],
     "portrait": None, "edited_by_human": False},
]}


def _ledger(pid: str) -> dict:
    return {
        "location": "the laboratory", "time_of_day": "night", "atmosphere": "lamplit, tense",
        "present": ["the Time Traveller"], "scene_changed": pid == "0001",
        "visual_salience": 0.8, "best_visual_beat": "the machine shudders and blurs at its edges",
        "carry_notes": "",
    }


@pytest.mark.skipif(not os.environ.get("TTS_URL"), reason="TTS_URL not set")
def test_live_prompts_pipeline(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SCRIPTORIUM_DATA", str(tmp_path))
    cfg = load_config()

    book = paginate(load(SourceSpec(kind=KIND_TEXT, path=_SOURCE, filename="pg35.txt")))
    root = cfg.work_dir / "live"
    pages_dir = root / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    page_ids = []
    for page in book.pages[:_N_PAGES]:
        page = {**page, "chapter": 1, "ledger": _ledger(page["id"])}
        (pages_dir / f"{page['id']}.json").write_text(
            json.dumps(page, ensure_ascii=False), encoding="utf-8")
        page_ids.append(page["id"])

    (root / "cast.json").write_text(json.dumps(_CAST), encoding="utf-8")
    (root / "selection.json").write_text(json.dumps({
        "preset": "classic",
        "params": {"min_gap": 2, "max_gap": 6, "salience_floor": 0.55,
                   "chapter_open": True, "scene_boundary": True},
        "plates": [{"page_id": pid, "reason": "chapter_open", "salience": 0.8,
                    "status": "selected", "added_in_revision": 1} for pid in page_ids],
    }), encoding="utf-8")

    Job(id="live", book_id="live", state=JobState.SELECTED, started=True,
        title="The Time Machine",
        bake_config={"style_id": "engraving", "density_preset": "classic",
                     "era": "late-Victorian England", "title": "The Time Machine",
                     "author": "H. G. Wells", "portraits_enabled": True}).save(cfg)

    runner = Runner(cfg, [PromptsEnter(), PromptsDerive()])
    for _ in range(60):
        asyncio.run(runner.tick())
        job = jobmod.load(cfg, "live")
        if job.state in {JobState.PROMPTS_DRAFT, JobState.FAILED}:
            break

    job = jobmod.load(cfg, "live")
    assert job.state == JobState.PROMPTS_DRAFT, f"ended in {job.state}, failed={job.failed_units}"

    prompts_dir = root / "prompts"
    print("\n=== live illustration prompts (first 3 pg35 pages) ===")
    for pid in page_ids:
        doc = json.loads((prompts_dir / f"{pid}.json").read_text("utf-8"))
        schemas.validate("prompt", doc)
        assert doc["final_subject_prompt"] == doc["derived"]["prompt"]
        print(f"  {pid}: {doc['final_subject_prompt'][:88]}")

    for pseudo in ("cover.json", "portrait-the-time-traveller.json"):
        doc = json.loads((prompts_dir / pseudo).read_text("utf-8"))
        schemas.validate("prompt", doc)
        print(f"  {pseudo}: {doc['final_subject_prompt'][:88]}")
    if job.prompt_warnings:
        print(f"  warnings: {job.prompt_warnings}")
