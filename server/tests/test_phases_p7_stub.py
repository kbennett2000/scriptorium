"""P7 render **stub** phase — the S9 demo render (DESIGN §10, §11.3).

Drives the real Runner over ``[RenderStub()]`` from ``approved`` and asserts the placeholder PNGs
land, page plates flip to ``rendered``, and ``job.render_stub`` is set. Image *content* is never
asserted — only that each file is a valid PNG of the plate size (CLAUDE.md).
"""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path

from PIL import Image

from scriptorium.bake import job as jobmod
from scriptorium.bake.job import Job, JobState
from scriptorium.bake.phases.p7_render_stub import RenderStub
from scriptorium.bake.runner import Runner
from scriptorium.config import Config
from scriptorium.render.imagegen import PLATE_SIZE


def _cfg(tmp_path) -> Config:
    return Config(
        data_dir=tmp_path, port=8720, tts_url=None, imagegen_url=None, gpu_mac=None,
        gpu_wol_enabled=False, runner_tick_s=1, shared_dir=tmp_path,
    )


async def _noop_sleep(_s: float) -> None:
    return None


def _runner(cfg: Config) -> Runner:
    return Runner(cfg, [RenderStub()], sleep=_noop_sleep, wake=lambda _c: None)


def _prompt_doc(page_id: str, prompt: str) -> dict:
    return {
        "page_id": page_id, "derived": {"prompt": prompt},
        "edited_prompt": None, "final_subject_prompt": prompt,
    }


def _seed(cfg: Config) -> None:
    book = cfg.work_dir / "b"
    (book / "prompts").mkdir(parents=True, exist_ok=True)
    for pid, text in [
        ("0001", "a lamplit workshop"),
        ("0003", "a clock tower at dusk"),
        ("cover", "frontispiece"),
        ("portrait-the-clockmaker", "a bust portrait"),
    ]:
        (book / "prompts" / f"{pid}.json").write_text(
            json.dumps(_prompt_doc(pid, text)), encoding="utf-8")
    (book / "selection.json").write_text(json.dumps({
        "preset": "classic",
        "params": {"min_gap": 2, "max_gap": 6, "salience_floor": 0.55,
                   "chapter_open": True, "scene_boundary": True},
        "plates": [
            {"page_id": "0001", "reason": "chapter_open", "salience": 0.8,
             "status": "approved", "added_in_revision": 1},
            {"page_id": "0003", "reason": "fill", "salience": 0.6,
             "status": "approved", "added_in_revision": 1},
        ],
    }), encoding="utf-8")
    Job(id="b", book_id="b", state=JobState.APPROVED, started=True).save(cfg)


def _drive(cfg: Config, max_ticks: int = 16) -> Job:
    runner = _runner(cfg)
    for _ in range(max_ticks):
        asyncio.run(runner.tick())
        job = jobmod.load(cfg, "b")
        if job.state in (JobState.RENDERING, JobState.FAILED):
            return job
    return jobmod.load(cfg, "b")


def _is_plate_png(path: Path) -> bool:
    img = Image.open(io.BytesIO(path.read_bytes()))
    img.verify()
    return Image.open(io.BytesIO(path.read_bytes())).size == PLATE_SIZE


def test_stub_renders_placeholders_and_marks_rendered(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _seed(cfg)
    job = _drive(cfg)
    assert job.state == JobState.RENDERING, f"stuck at {job.state}"
    assert job.render_stub is True

    plates = cfg.work_dir / "b" / "images" / "plates"
    for pid in ("0001", "0003", "cover", "portrait-the-clockmaker"):
        assert _is_plate_png(plates / f"{pid}.png"), pid

    # Page plates flip to rendered; pseudo-plates have no selection entry to touch.
    selection = json.loads((cfg.work_dir / "b" / "selection.json").read_text("utf-8"))
    assert {p["page_id"]: p["status"] for p in selection["plates"]} == {
        "0001": "rendered", "0003": "rendered",
    }


def test_stub_is_idempotent(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _seed(cfg)
    _drive(cfg)
    png = cfg.work_dir / "b" / "images" / "plates" / "0001.png"
    first = png.read_bytes()

    # Re-run the phase from approved: unit_done sees the PNGs and skips them, bytes unchanged.
    job = jobmod.load(cfg, "b")
    job.state = JobState.APPROVED
    job.save(cfg)
    _drive(cfg)
    assert png.read_bytes() == first
