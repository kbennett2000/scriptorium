"""Auto-approve runner path (ADR-0015): the ``AUTO_APPROVE`` opt-in that lets the runner clear
the review gate itself on a single-user box.

The shared :func:`~scriptorium.bake.approve.approve_job` logic is already exercised through the
review endpoint (``test_review_api.py``); here we prove the *runner wiring*:

- with ``auto_approve=True`` a job resting at ``prompts_draft`` is advanced past the gate,
- with it off (the default) the job stays parked — invariant #4 preserved,
- a renderable plate missing its prompt is NOT auto-approved (the guard still bites).

Assertions are state/shape only — never image content. No GPU: the pipeline used here is just the
review-gate hop, so the job reaches ``approved`` and stops (no render phase registered).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from scriptorium.bake import job as jobmod
from scriptorium.bake.job import Job, JobState
from scriptorium.bake.runner import Runner
from scriptorium.config import Config


def _cfg(tmp_path: Path, **overrides) -> Config:
    base = dict(
        data_dir=tmp_path, port=8720, tts_url=None, imagegen_url=None, gpu_mac=None,
        gpu_wol_enabled=False, runner_tick_s=1, shared_dir=tmp_path,
    )
    base.update(overrides)
    return Config(**base)


def _seed_prompts_draft(cfg: Config, *, with_prompts: bool = True) -> Job:
    """A job resting at ``prompts_draft`` with a selection.json and (optionally) its prompts."""
    book = cfg.work_dir / "b"
    (book / "prompts").mkdir(parents=True, exist_ok=True)
    selection = {
        "preset": "classic",
        "params": {"min_gap": 2, "max_gap": 6, "salience_floor": 0.55,
                   "chapter_open": True, "scene_boundary": True},
        "plates": [
            {"page_id": "0001", "reason": "chapter_open", "salience": 0.82,
             "status": "selected", "added_in_revision": 1},
            {"page_id": "0003", "reason": "fill", "salience": 0.6,
             "status": "selected", "added_in_revision": 1},
        ],
    }
    (book / "selection.json").write_text(json.dumps(selection), encoding="utf-8")
    if with_prompts:
        for pid in ("0001", "0003"):
            (book / "prompts" / f"{pid}.json").write_text(
                json.dumps({"page_id": pid, "derived": {"prompt": "x"},
                            "edited_prompt": None, "final_subject_prompt": "x"}),
                encoding="utf-8",
            )
    job = Job(id="b", book_id="b", state=JobState.PROMPTS_DRAFT, started=True)
    job.save(cfg)
    return job


# The review-gate hop is a pure rest-to-rest transition, so a runner with an empty pipeline still
# advances it: `approve_job` moves the job to `approved`, which has no phase → it rests there.


def test_auto_approve_clears_the_gate_and_locks_the_shot_list(tmp_path) -> None:
    cfg = _cfg(tmp_path, auto_approve=True)
    _seed_prompts_draft(cfg)
    runner = Runner(cfg, pipeline=[])

    asyncio.run(runner.tick())

    job = jobmod.load(cfg, "b")
    assert job.state == JobState.APPROVED
    selection = json.loads((cfg.work_dir / "b" / "selection.json").read_text("utf-8"))
    assert {p["status"] for p in selection["plates"]} == {"approved"}


def test_default_leaves_the_job_parked_for_the_human_gate(tmp_path) -> None:
    cfg = _cfg(tmp_path)  # auto_approve defaults to False
    _seed_prompts_draft(cfg)
    runner = Runner(cfg, pipeline=[])

    asyncio.run(runner.tick())

    assert jobmod.load(cfg, "b").state == JobState.PROMPTS_DRAFT


def test_auto_approve_still_refuses_a_plate_without_a_prompt(tmp_path) -> None:
    cfg = _cfg(tmp_path, auto_approve=True)
    _seed_prompts_draft(cfg, with_prompts=False)  # selected plates lack prompt artifacts
    runner = Runner(cfg, pipeline=[])

    asyncio.run(runner.tick())

    # The guard bites even on the auto path: the job stays parked rather than reaching render.
    assert jobmod.load(cfg, "b").state == JobState.PROMPTS_DRAFT
