"""P1→P2 integration over recorded fixtures, driven through the real runner (DESIGN §7).

Uses respx to stand in for the TTS. ``cast-mentions`` is answered per page from the
hand-written fixtures; ``cast-canonicalize`` from the named fixtures where present, else a
generic schema-valid canon. Asserts the acceptance criteria: a schema-valid ``cast.json``
with the Time Traveller major + a sane alias set, resume skipping done units, and each TTS
error code producing the correct job outcome (waiting_gpu / failed_units / failed).

The runner coroutines are driven with ``asyncio.run`` (no pytest-asyncio); ``gpu_gate`` is
forced up and ``sleep``/``wake`` are no-ops so the retry ladder and WoL don't slow the run.
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
from scriptorium.bake.phases.p1_mentions import CastMentions, MentionsEnter
from scriptorium.bake.phases.p2_cast import CastCanonicalize, CastReduce
from scriptorium.bake.reduce_cast import _slug
from scriptorium.bake.runner import Runner
from scriptorium.config import Config

TTS = "http://tts.test:8712"
_FIX = Path(__file__).parent / "fixtures" / "tts"
_MENTIONS_URL = f"{TTS}/v1/transform/cast-mentions"
_CANON_URL = f"{TTS}/v1/transform/cast-canonicalize"

_GENERIC_CANON = {
    "output": {
        "visual_description": "A figure described plainly enough for a painter to render.",
        "one_line": "A plainly described figure",
        "tags": ["figure", "plain", "generic"],
    },
    "meta": {},
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
    pipeline = [MentionsEnter(), CastMentions(), CastReduce(), CastCanonicalize()]
    return Runner(cfg, pipeline, sleep=_noop_sleep, wake=lambda _c: None, gpu_gate=_gate_up)


def _seed_job(cfg: Config, n_pages: int = 6, state: str = JobState.INGESTED) -> Job:
    pages = cfg.work_dir / "b" / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    for i in range(1, n_pages + 1):
        pid = f"{i:04d}"
        (pages / f"{pid}.json").write_text(
            json.dumps({"id": pid, "seq": i, "chapter": 1,
                        "text": f"PAGE {pid}", "word_count": 2}),
            encoding="utf-8",
        )
    job = Job(id="b", book_id="b", state=state, started=True)
    job.save(cfg)
    return job


def _mentions_fixture(pid: str) -> dict[str, Any]:
    return json.loads((_FIX / "cast-mentions" / f"{pid}.json").read_text(encoding="utf-8"))


def _mentions_handler(request: httpx.Request) -> httpx.Response:
    text = json.loads(request.content)["text"]
    pid = text.split()[-1]  # "PAGE 0001" -> "0001"
    return httpx.Response(200, json=_mentions_fixture(pid))


def _canon_handler(request: httpx.Request) -> httpx.Response:
    name = json.loads(request.content)["options"]["name"]
    fixture = _FIX / "cast-canonicalize" / f"{_slug(name)}.json"
    if fixture.is_file():
        return httpx.Response(200, json=json.loads(fixture.read_text(encoding="utf-8")))
    return httpx.Response(200, json=_GENERIC_CANON)


def _drive(cfg: Config, runner: Runner, *, stop_states: set[str], max_ticks: int = 12) -> Job:
    for _ in range(max_ticks):
        asyncio.run(runner.tick())
        job = jobmod.load(cfg, "b")
        if job.state in stop_states:
            return job
    return jobmod.load(cfg, "b")


_TERMINAL = {JobState.CAST_DONE, JobState.FAILED, JobState.WAITING_GPU}


# --- full happy path --------------------------------------------------------


@respx.mock
def test_full_p1_p2_produces_schema_valid_cast(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _seed_job(cfg)
    mentions = respx.post(_MENTIONS_URL).mock(side_effect=_mentions_handler)
    respx.post(_CANON_URL).mock(side_effect=_canon_handler)

    job = _drive(cfg, _runner(cfg), stop_states={JobState.CAST_DONE})

    assert job.state == JobState.CAST_DONE
    assert job.failed_units == []
    assert mentions.call_count == 6  # one call per page, none repeated

    doc = json.loads((cfg.work_dir / "b" / "cast.json").read_text(encoding="utf-8"))
    schemas.validate("cast", doc)  # acceptance: schema-valid cast.json
    by_slug = {c["slug"]: c for c in doc["characters"]}

    tt = by_slug["time-traveller"]
    assert tt["major"] is True
    assert isinstance(tt["aliases"], list)  # aliases collected (shape, not exact wording)
    assert tt["visual_description"] is not None  # majors are canonicalized
    # Structural invariant, narrative-independent: a character carries a visual_description
    # iff it is a major. (Real captures over the first 6 pages are all-majors, so the
    # non-major branch is vacuous on this slice, but the contract is still asserted.)
    for c in doc["characters"]:
        assert (c["visual_description"] is not None) == bool(c["major"])


def test_reduce_output_matches_cast_schema_shape() -> None:
    # Sanity: the fixtures reduce to a Time Traveller major with a well-formed alias set,
    # independent of the HTTP path (guards against fixture drift). Shape, not exact aliases.
    from scriptorium.bake.reduce_cast import reduce_cast

    pages = [
        {"page_id": p, "mentions": _mentions_fixture(p)["output"]["mentions"]}
        for p in ["0001", "0002", "0003", "0004", "0005", "0006"]
    ]
    groups = {g["slug"]: g for g in reduce_cast(pages)}
    assert groups["time-traveller"]["major"] is True
    assert isinstance(groups["time-traveller"]["aliases"], list)


# --- resume skips completed units ------------------------------------------


@respx.mock
def test_resume_skips_already_done_mention_pages(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _seed_job(cfg, state=JobState.MENTIONS_RUNNING)
    # Pre-write 3 of 6 mention artifacts (as if a prior run completed them).
    mdir = cfg.work_dir / "b" / "mentions"
    mdir.mkdir(parents=True, exist_ok=True)
    for pid in ["0001", "0002", "0003"]:
        (mdir / f"{pid}.json").write_text(json.dumps({"mentions": []}), encoding="utf-8")
    mentions = respx.post(_MENTIONS_URL).mock(side_effect=_mentions_handler)

    job = jobmod.load(cfg, "b")
    asyncio.run(_runner(cfg).advance_job(job))

    assert mentions.call_count == 3  # only the 3 missing pages were re-requested
    assert job.state == JobState.MENTIONS_DONE
    assert sorted(p.stem for p in mdir.glob("*.json")) == \
        ["0001", "0002", "0003", "0004", "0005", "0006"]


# --- waiting_gpu: P1 503 --------------------------------------------------


@respx.mock
def test_p1_503_parks_waiting_gpu_then_resumes(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _seed_job(cfg)
    state = {"down": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["down"]:
            return httpx.Response(503, json={"error": {"code": "busy"}})
        return _mentions_handler(request)

    respx.post(_MENTIONS_URL).mock(side_effect=handler)
    respx.post(_CANON_URL).mock(side_effect=_canon_handler)
    runner = _runner(cfg)

    parked = _drive(cfg, runner, stop_states={JobState.WAITING_GPU})
    assert parked.state == JobState.WAITING_GPU
    assert parked.prev_state == JobState.MENTIONS_RUNNING

    state["down"] = False  # GPU back
    done = _drive(cfg, runner, stop_states={JobState.CAST_DONE})
    assert done.state == JobState.CAST_DONE
    assert done.failed_units == []


# --- waiting_gpu: P2 canonicalize 503 (the cast_running state) --------------


@respx.mock
def test_p2_canonicalize_503_parks_on_cast_running(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _seed_job(cfg)
    respx.post(_MENTIONS_URL).mock(side_effect=_mentions_handler)
    state = {"down": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["down"]:
            return httpx.Response(503, json={"error": {"code": "model_unavailable"}})
        return _canon_handler(request)

    respx.post(_CANON_URL).mock(side_effect=handler)
    runner = _runner(cfg)

    parked = _drive(cfg, runner, stop_states={JobState.WAITING_GPU})
    assert parked.state == JobState.WAITING_GPU
    assert parked.prev_state == JobState.CAST_RUNNING  # P2b parks (S5 cast_running addition)

    state["down"] = False
    done = _drive(cfg, runner, stop_states={JobState.CAST_DONE})
    assert done.state == JobState.CAST_DONE


# --- 422: unit ladder → failed_units, phase still completes -----------------


@respx.mock
def test_canonicalize_422_records_failed_unit_and_completes(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _seed_job(cfg)
    respx.post(_MENTIONS_URL).mock(side_effect=_mentions_handler)

    def handler(request: httpx.Request) -> httpx.Response:
        name = json.loads(request.content)["options"]["name"]
        if _slug(name) == "time-traveller":
            return httpx.Response(422, json={"error": {"code": "validation_failed",
                                                       "detail": {"reasons": ["banned"]}}})
        return _canon_handler(request)

    respx.post(_CANON_URL).mock(side_effect=handler)

    job = _drive(cfg, _runner(cfg), stop_states={JobState.CAST_DONE})

    assert job.state == JobState.CAST_DONE  # phase completed despite the failed unit
    failed = [f for f in job.failed_units if f["unit"] == "time-traveller"]
    assert failed and failed[0]["phase"] == "p2_canonicalize"
    doc = json.loads((cfg.work_dir / "b" / "cast.json").read_text(encoding="utf-8"))
    tt = next(c for c in doc["characters"] if c["slug"] == "time-traveller")
    assert tt["visual_description"] is None  # left un-canonicalized, still schema-valid
    schemas.validate("cast", doc)


# --- bug-class: 400 halts the job loudly ------------------------------------


@respx.mock
def test_mentions_400_fails_the_job(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _seed_job(cfg)
    respx.post(_MENTIONS_URL).mock(
        return_value=httpx.Response(400, json={"error": {"code": "bad_request"}})
    )

    job = _drive(cfg, _runner(cfg), stop_states={JobState.FAILED})
    assert job.state == JobState.FAILED
