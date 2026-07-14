"""Live P7 over real imagegen-service (``-m gpu``, opt-in; skipped by the default offline run).

Renders two real plates through the actual imagegen-service on the LAN, asserting only that pixels
land at the §10 plate size and that the §7.4 unload-first sequencing observably happened (after the
render, TTS ``/health`` reports no models loaded). Never asserts image content (CLAUDE.md).
Requires both ``TTS_URL`` (for the unload handoff) and ``IMAGEGEN_URL`` to point at reachable
services, and the imagegen-service size PR (S10a) deployed so 832×1216 is honored.

    cd server && TTS_URL=http://<host>:8712 IMAGEGEN_URL=http://<gpu-box>:8189 \
        uv run pytest -m gpu test_render_live.py -s
"""

from __future__ import annotations

import asyncio
import io
import json
import os

import httpx
import pytest
from PIL import Image

from scriptorium import schemas
from scriptorium.bake import job as jobmod
from scriptorium.bake.job import Job, JobState
from scriptorium.bake.phases.p7_render import Render, RenderEnter
from scriptorium.bake.runner import Runner
from scriptorium.config import load_config

pytestmark = pytest.mark.gpu

_N_PLATES = 2


def _prompt(page_id: str, subject: str) -> dict:
    return {"page_id": page_id, "derived": {"prompt": subject, "avoid": ["color", "modern dress"]},
            "edited_prompt": None, "final_subject_prompt": subject}


@pytest.mark.skipif(
    not (os.environ.get("TTS_URL") and os.environ.get("IMAGEGEN_URL")),
    reason="TTS_URL and IMAGEGEN_URL must both be set",
)
def test_live_render_two_plates(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SCRIPTORIUM_DATA", str(tmp_path))
    cfg = load_config()

    root = cfg.work_dir / "live"
    prompts = root / "prompts"
    prompts.mkdir(parents=True, exist_ok=True)
    subjects = [
        ("0001", "a lean Victorian inventor beside a brass time machine in a lamplit laboratory"),
        ("0002", "a vast twilight landscape of ruined white sphinxes under a swollen red sun"),
    ]
    for pid, subject in subjects[:_N_PLATES]:
        (prompts / f"{pid}.json").write_text(json.dumps(_prompt(pid, subject)), encoding="utf-8")
    (root / "selection.json").write_text(json.dumps({
        "preset": "classic",
        "params": {"min_gap": 2, "max_gap": 6, "salience_floor": 0.55,
                   "chapter_open": True, "scene_boundary": True},
        "plates": [{"page_id": pid, "reason": "chapter_open", "salience": 0.8,
                    "status": "approved", "added_in_revision": 1}
                   for pid, _ in subjects[:_N_PLATES]],
    }), encoding="utf-8")

    Job(id="live", book_id="live", state=JobState.APPROVED, started=True,
        title="The Time Machine",
        bake_config={"style_id": "engraving", "density_preset": "classic",
                     "author": "H. G. Wells"}).save(cfg)

    runner = Runner(cfg, [RenderEnter(), Render()])
    for _ in range(60):
        asyncio.run(runner.tick())
        job = jobmod.load(cfg, "live")
        if job.state in {JobState.RENDERED, JobState.FAILED}:
            break
    job = jobmod.load(cfg, "live")
    assert job.state == JobState.RENDERED, f"ended in {job.state}, failed={job.failed_units}"

    print("\n=== live render (2 real plates) ===")
    for pid, _ in subjects[:_N_PLATES]:
        png = root / "images" / "plates" / f"{pid}.png"
        assert png.is_file(), pid
        assert Image.open(io.BytesIO(png.read_bytes())).size == (832, 1216), pid
        assert (root / "images" / "web" / "plates" / f"{pid}.webp").is_file()
        doc = json.loads((root / "prompts" / f"{pid}.json").read_text("utf-8"))
        schemas.validate("prompt", doc)
        print(f"  {pid}: {png.stat().st_size} bytes, seed={doc['render']['params_echo']['seed']}")

    # §7.4 observable sequencing: after render the TTS has unloaded its models.
    health = httpx.get(os.environ["TTS_URL"].rstrip("/") + "/health", timeout=15.0).json()
    print(f"  TTS after render: models_loaded={health.get('models_loaded')}")
    assert not health.get("models_loaded"), "TTS models should be unloaded before render (§7.4)"
