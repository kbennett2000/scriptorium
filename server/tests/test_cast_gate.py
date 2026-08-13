"""Cast-review gate (ADR-0032): approve character descriptions before the scene prompts derive.

The gate is always on and behaves like ``prompts_draft`` — it rests for a human and is only
auto-advanced under ``AUTO_APPROVE``. These tests prove:

- the runner rests at ``cast_done`` by default and auto-advances it to ``cast_approved`` under
  ``auto_approve`` (mirroring ``test_auto_approve``);
- ``approve_cast``'s missing-description guard refuses a blank major on both paths;
- ``present_cast`` folds the approved ``visual_description`` into the scene-cast option.

State/shape assertions only, no GPU: the pipeline used here is just the gate hop, so the job
reaches ``cast_approved`` and rests (no ledger phase registered).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from scriptorium.bake import job as jobmod
from scriptorium.bake.approve import CastApprovalBlocked, approve_cast
from scriptorium.bake.job import Job, JobState
from scriptorium.bake.phases.p5_prompts import present_cast
from scriptorium.bake.runner import Runner
from scriptorium.config import Config


def _cfg(tmp_path: Path, **overrides) -> Config:
    base = dict(
        data_dir=tmp_path, port=8720, tts_url=None, imagegen_url=None, gpu_mac=None,
        gpu_wol_enabled=False, runner_tick_s=1, shared_dir=tmp_path,
    )
    base.update(overrides)
    return Config(**base)


def _char(slug, name, *, major=True, one_line="a hero", vd="tall, with a grey beard") -> dict:
    return {
        "slug": slug, "name": name, "aliases": [], "mention_pages": ["0001"], "major": major,
        "visual_description": vd, "one_line": one_line, "tags": [],
        "portrait": None, "edited_by_human": False,
    }


def _seed_cast_done(cfg: Config, characters: list[dict]) -> Job:
    """A job resting at ``cast_done`` with a schema-shaped cast.json."""
    book = cfg.work_dir / "b"
    book.mkdir(parents=True, exist_ok=True)
    (book / "cast.json").write_text(json.dumps({"characters": characters}), encoding="utf-8")
    job = Job(id="b", book_id="b", state=JobState.CAST_DONE, started=True)
    job.save(cfg)
    return job


# The gate hop is a pure rest-to-rest transition, so a runner with an empty pipeline still advances
# it: `approve_cast` moves the job to `cast_approved`, which has no phase here → it rests there.


def test_auto_approve_clears_the_cast_gate(tmp_path) -> None:
    cfg = _cfg(tmp_path, auto_approve=True)
    _seed_cast_done(cfg, [_char("a", "A"), _char("b", "B")])
    runner = Runner(cfg, pipeline=[])

    asyncio.run(runner.tick())

    assert jobmod.load(cfg, "b").state == JobState.CAST_APPROVED


def test_default_leaves_the_job_parked_at_the_cast_gate(tmp_path) -> None:
    cfg = _cfg(tmp_path)  # auto_approve defaults to False
    _seed_cast_done(cfg, [_char("a", "A")])
    runner = Runner(cfg, pipeline=[])

    asyncio.run(runner.tick())

    assert jobmod.load(cfg, "b").state == JobState.CAST_DONE


def test_auto_approve_refuses_a_major_with_no_description(tmp_path) -> None:
    cfg = _cfg(tmp_path, auto_approve=True)
    _seed_cast_done(cfg, [_char("a", "A"), _char("b", "B", vd="   ")])  # B has a blank description
    runner = Runner(cfg, pipeline=[])

    asyncio.run(runner.tick())

    # The guard bites even on the auto path: the job stays parked for a human.
    assert jobmod.load(cfg, "b").state == JobState.CAST_DONE


def test_approve_cast_blocks_blank_major_and_lists_slugs(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    job = _seed_cast_done(cfg, [
        _char("hero", "Hero"),
        _char("ghost", "Ghost", one_line=""),          # blank one_line
        _char("blur", "Blur", vd=""),                   # blank description
        _char("extra", "Extra", major=False, vd=""),    # minor: not guarded
    ])
    with pytest.raises(CastApprovalBlocked) as exc:
        approve_cast(cfg, job)
    assert exc.value.slugs == ["blur", "ghost"]          # sorted; minor excluded
    assert jobmod.load(cfg, "b").state == JobState.CAST_DONE  # no transition on failure


def test_approve_cast_advances_when_all_majors_described(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    job = _seed_cast_done(cfg, [_char("a", "A"), _char("b", "B", major=False, vd="")])
    approve_cast(cfg, job)
    assert jobmod.load(cfg, "b").state == JobState.CAST_APPROVED


def test_approve_cast_rejects_wrong_state(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _seed_cast_done(cfg, [_char("a", "A")])
    job = jobmod.load(cfg, "b")
    job.state = JobState.CAST_APPROVED  # already past the gate
    with pytest.raises(ValueError, match="cannot approve cast"):
        approve_cast(cfg, job)


def test_present_cast_folds_in_approved_appearance() -> None:
    cast = {"characters": [
        _char("a", "A", one_line="a knight", vd="A tall man with a grey beard."),
        _char("b", "B", vd=""),  # no description → no appearance key
    ]}
    out = present_cast(cast, {"present": ["A", "B"]})
    by_name = {c["name"]: c for c in out}
    assert "appearance" in by_name["A"] and by_name["A"]["appearance"]
    assert "A" not in by_name["A"]["appearance"]  # subject stripped (no "A tall man" duplication)
    assert "appearance" not in by_name["B"]       # blank description contributes nothing
