"""P5 prompt-derivation phase over recorded fixtures, driven through the real runner (§7.1, §10).

respx stands in for the TTS ``illustration-prompt`` transform, answered per page from the
hand-written fixtures (or a generic valid response for pages without one). Asserts the P5
contract: one draft ``prompts/{page}.json`` per *selected* page with ``derived`` stored verbatim
and ``final_subject_prompt == derived.prompt``; the CPU-assembled ``cover`` + ``portrait-{slug}``
pseudo-plates; per-page ``meta.warnings`` captured onto ``job.prompt_warnings``; and idempotent
resume. Runner coroutines are driven with ``asyncio.run``; the GPU gate is forced up.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import respx

from scriptorium import schemas
from scriptorium.bake import job as jobmod
from scriptorium.bake.job import Job, JobState
from scriptorium.bake.phases.p5_prompts import (
    PromptsDerive,
    PromptsEnter,
    assemble_cover,
    assemble_portrait,
)
from scriptorium.bake.runner import Runner
from scriptorium.config import Config
from scriptorium.styles import get_style

TTS = "http://tts.test:8712"
_FIX = Path(__file__).parent / "fixtures" / "tts" / "illustration-prompt"
_URL = f"{TTS}/v1/transform/illustration-prompt"

_TITLE = "The Tidewatch Fragment"
_AUTHOR = "A. Fixture"
_ERA = "an imagined coastal town"
_SELECTED = ["0001", "0003", "0004"]

_CLOCKMAKER = {
    "slug": "the-clockmaker", "name": "the Clockmaker", "aliases": ["the old clockmaker"],
    "mention_pages": ["0001", "0002", "0003"], "major": True,
    "visual_description": "a spare, white-haired artisan in a leather apron",
    "one_line": "The keeper of the workshop at the end of the lane.",
    "tags": ["artisan"], "portrait": None, "edited_by_human": False,
}
_STRANGER = {
    "slug": "the-stranger", "name": "the Stranger", "aliases": [],
    "mention_pages": ["0004"], "major": False, "visual_description": None,
    "one_line": "A pale visitor who arrives with the winter tide.",
    "tags": [], "portrait": None, "edited_by_human": False,
}


def _cfg(tmp_path) -> Config:
    return Config(
        data_dir=tmp_path, port=8720, tts_url=TTS, imagegen_url=None, gpu_mac=None,
        gpu_wol_enabled=False, runner_tick_s=1, shared_dir=tmp_path,
    )


async def _gate_up(_cfg: Config) -> bool:
    return True


async def _noop_sleep(_s: float) -> None:
    return None


def _runner(cfg: Config) -> Runner:
    pipeline = [PromptsEnter(), PromptsDerive()]
    return Runner(cfg, pipeline, sleep=_noop_sleep, wake=lambda _c: None, gpu_gate=_gate_up)


def _ledger(pid: str, *, salience: float, beat: str, present: list[str]) -> dict[str, Any]:
    return {
        "location": "", "time_of_day": "unknown", "atmosphere": "", "present": present,
        "scene_changed": False, "visual_salience": salience, "best_visual_beat": beat,
        "carry_notes": "",
    }


# Six pages: chapter 1 = 0001..0003 (0002 is the chapter-1 salience peak → cover beat),
# chapter 2 = 0004..0006. Text is ``PAGE {id}`` so the handler keys fixtures by id.
_COVER_BEAT = "a quiet harbour at dawn"
_PAGES = [
    ("0001", 1, 1, 0.60, "workshop lamplight", ["the Clockmaker"]),
    ("0002", 2, 1, 0.95, _COVER_BEAT, ["the old clockmaker"]),
    ("0003", 3, 1, 0.55, "a ticking bench", ["the Clockmaker"]),
    ("0004", 4, 2, 0.70, "the winter tide", ["the Stranger"]),
    ("0005", 5, 2, 0.40, "an empty lane", []),
    ("0006", 6, 2, 0.50, "a shuttered door", []),
]


def _write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _seed(cfg: Config, *, portraits_enabled: bool = True) -> Job:
    book = cfg.work_dir / "b"
    for pid, seq, chapter, salience, beat, present in _PAGES:
        _write(book / "pages" / f"{pid}.json", {
            "id": pid, "seq": seq, "chapter": chapter, "text": f"PAGE {pid}", "word_count": 2,
            "ledger": _ledger(pid, salience=salience, beat=beat, present=present),
        })
    _write(book / "cast.json", {"characters": [_CLOCKMAKER, _STRANGER]})
    _write(book / "selection.json", {
        "preset": "classic",
        "params": {"min_gap": 2, "max_gap": 6, "salience_floor": 0.55,
                   "chapter_open": True, "scene_boundary": True},
        "plates": [
            {"page_id": pid, "reason": "chapter_open", "salience": 0.6,
             "status": "selected", "added_in_revision": 1}
            for pid in _SELECTED
        ] + [
            # A non-selected plate must NOT get a prompt.
            {"page_id": "0006", "reason": "fill", "salience": 0.5,
             "status": "retired", "added_in_revision": 1},
        ],
    })
    job = Job(id="b", book_id="b", state=JobState.SELECTED, started=True, title=_TITLE,
              bake_config={"style_id": "engraving", "density_preset": "classic", "era": _ERA,
                           "title": _TITLE, "author": _AUTHOR,
                           "portraits_enabled": portraits_enabled})
    job.save(cfg)
    return job


def _fixture_output(pid: str) -> dict[str, Any]:
    return json.loads((_FIX / f"{pid}.json").read_text("utf-8"))["output"]


def _generic_envelope(pid: str) -> dict[str, Any]:
    return {"output": {"prompt": f"a generic valid illustration subject for page {pid} here",
                       "depicted": [], "shot": "medium", "avoid": []},
            "meta": {"transform": "illustration-prompt", "attempts": 1}}


def _handler(request: httpx.Request) -> httpx.Response:
    pid = json.loads(request.content)["text"].split()[-1]
    fix = _FIX / f"{pid}.json"
    if fix.is_file():
        return httpx.Response(200, json=json.loads(fix.read_text("utf-8")))
    return httpx.Response(200, json=_generic_envelope(pid))


def _drive(cfg: Config, runner: Runner, *, stop: set[str], max_ticks: int = 12) -> Job:
    for _ in range(max_ticks):
        asyncio.run(runner.tick())
        job = jobmod.load(cfg, "b")
        if job.state in stop:
            return job
    return jobmod.load(cfg, "b")


def _prompt(cfg: Config, page_id: str) -> dict[str, Any]:
    return json.loads((cfg.work_dir / "b" / "prompts" / f"{page_id}.json").read_text("utf-8"))


# --- per-page derivation ----------------------------------------------------


@respx.mock
def test_derives_schema_valid_prompt_per_selected_page(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _seed(cfg)
    respx.post(_URL).mock(side_effect=_handler)

    job = _drive(cfg, _runner(cfg), stop={JobState.PROMPTS_DRAFT})
    assert job.state == JobState.PROMPTS_DRAFT
    assert job.failed_units == []

    for pid in _SELECTED:
        doc = _prompt(cfg, pid)
        schemas.validate("prompt", doc)
        assert doc["page_id"] == pid
        assert doc["derived"] == _fixture_output(pid)  # stored verbatim
        assert doc["edited_prompt"] is None
        assert doc["final_subject_prompt"] == doc["derived"]["prompt"]
        # style-wrapping fields stay absent until P7.
        assert "wrapped_prompt" not in doc and "negative_prompt" not in doc

    # A non-selected (retired) plate never gets a prompt file.
    assert not (cfg.work_dir / "b" / "prompts" / "0006.json").is_file()


@respx.mock
def test_meta_warnings_recorded_on_job(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _seed(cfg)
    respx.post(_URL).mock(side_effect=_handler)

    _drive(cfg, _runner(cfg), stop={JobState.PROMPTS_DRAFT})
    job = jobmod.load(cfg, "b")
    # meta.warnings on a selected page's fixture are recorded onto the job, keyed by page id
    # (shape/cross-ref only — which page carries the warning, and its wording, vary with the
    # capture; never assert exact LLM content).
    assert isinstance(job.prompt_warnings, dict) and job.prompt_warnings
    for pid, warns in job.prompt_warnings.items():
        assert isinstance(pid, str) and pid.isdigit()  # keyed by a page id
        assert isinstance(warns, list) and warns
        assert all(isinstance(w, str) for w in warns)


# --- cover + portrait pseudo-plates (DESIGN §10) ----------------------------


@respx.mock
def test_cover_pseudo_plate_matches_formula(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _seed(cfg)
    respx.post(_URL).mock(side_effect=_handler)

    _drive(cfg, _runner(cfg), stop={JobState.PROMPTS_DRAFT})
    doc = _prompt(cfg, "cover")
    schemas.validate("prompt", doc)
    assert doc["page_id"] == "cover"
    expected = assemble_cover(get_style("engraving"), _TITLE, _AUTHOR, _COVER_BEAT)
    assert doc["final_subject_prompt"] == expected
    assert doc["derived"] == {"prompt": expected}
    assert doc["edited_prompt"] is None


@respx.mock
def test_portrait_pseudo_plate_for_major_only(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _seed(cfg)
    respx.post(_URL).mock(side_effect=_handler)

    _drive(cfg, _runner(cfg), stop={JobState.PROMPTS_DRAFT})
    # The major (clockmaker) gets a portrait; the minor (stranger, null description) does not.
    doc = _prompt(cfg, "portrait-the-clockmaker")
    schemas.validate("prompt", doc)
    expected = assemble_portrait(
        get_style("engraving"), _CLOCKMAKER["one_line"], _CLOCKMAKER["visual_description"]
    )
    assert doc["final_subject_prompt"] == expected
    assert not (cfg.work_dir / "b" / "prompts" / "portrait-the-stranger.json").is_file()


@respx.mock
def test_portraits_disabled_emits_no_portrait(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _seed(cfg, portraits_enabled=False)
    respx.post(_URL).mock(side_effect=_handler)

    job = _drive(cfg, _runner(cfg), stop={JobState.PROMPTS_DRAFT})
    assert job.state == JobState.PROMPTS_DRAFT
    assert not (cfg.work_dir / "b" / "prompts" / "portrait-the-clockmaker.json").is_file()
    # Cover is always produced, portraits or not.
    assert (cfg.work_dir / "b" / "prompts" / "cover.json").is_file()


# --- idempotent resume ------------------------------------------------------


@respx.mock
def test_existing_prompt_is_not_overwritten(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _seed(cfg, portraits_enabled=False)
    # Pre-write a sentinel prompt for 0001 as if a prior run produced it.
    sentinel = {"page_id": "0001", "derived": {"prompt": "SENTINEL do not touch"},
                "edited_prompt": None, "final_subject_prompt": "SENTINEL do not touch"}
    _write(cfg.work_dir / "b" / "prompts" / "0001.json", sentinel)
    respx.post(_URL).mock(side_effect=_handler)

    job = _drive(cfg, _runner(cfg), stop={JobState.PROMPTS_DRAFT})
    assert job.state == JobState.PROMPTS_DRAFT
    assert _prompt(cfg, "0001") == sentinel  # untouched (unit_done short-circuited)
