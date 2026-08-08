"""P3 scene-ledger phase over recorded fixtures, driven through the real runner (DESIGN §7.3).

Uses respx to stand in for the TTS ``scene-update`` transform, answered per page from the
hand-written fixtures. A recording handler captures each call's posted ``options.prior_ledger``
so the load-bearing **threading** property can be asserted directly: call N is fed exactly the
ledger returned for call N−1, and page 1 is fed ``null``.

Also covers the two other §7.3 behaviours P3 adds over P1/P2: **contiguity resume** (restart at
the first missing ledger, threading from its stored predecessor) and the **gap rule** (a
permanently-failed page inherits its predecessor's ledger + a ``carry_notes`` annotation, applied
at phase end so the real ledger could still fill first).

Runner coroutines are driven with ``asyncio.run`` (no pytest-asyncio); ``gpu_gate`` is forced up
and ``sleep``/``wake`` are no-ops so the retry ladder and WoL don't slow the run.
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
from scriptorium.bake.phases.p3_ledger import LedgerEnter, LedgerScenes
from scriptorium.bake.runner import Runner
from scriptorium.config import Config

TTS = "http://tts.test:8712"
_FIX = Path(__file__).parent / "fixtures" / "tts" / "scene-update"
_SCENE_URL = f"{TTS}/v1/transform/scene-update"
_PAGE_IDS = ["0001", "0002", "0003", "0004", "0005", "0006"]


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
    pipeline = [LedgerEnter(), LedgerScenes()]
    return Runner(cfg, pipeline, sleep=_noop_sleep, wake=lambda _c: None, gpu_gate=_gate_up)


def _ledger_fixture(pid: str) -> dict[str, Any]:
    """The verbatim ``output`` (the ledger) for a page fixture."""
    env = json.loads((_FIX / f"{pid}.json").read_text(encoding="utf-8"))
    return env["output"]


def _scene_envelope(pid: str) -> dict[str, Any]:
    return json.loads((_FIX / f"{pid}.json").read_text(encoding="utf-8"))


def _seed_job(cfg: Config, n_pages: int = 6, state: str = JobState.CAST_DONE) -> Job:
    """Seed pages (text ``PAGE {id}``) + a minimal cast.json, at the given state."""
    book = cfg.work_dir / "b"
    pages = book / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    for i in range(1, n_pages + 1):
        pid = f"{i:04d}"
        # >3 words so the near-empty neutral-ledger backstop (p3_ledger) does not fire; the
        # recording handler still recovers the id from the last token.
        (pages / f"{pid}.json").write_text(
            json.dumps({"id": pid, "seq": i, "chapter": 1,
                        "text": f"page body text {pid}", "word_count": 4}),
            encoding="utf-8",
        )
    # P3 reads canonical names from cast.json for the scene-update ``cast_names`` option.
    (book / "cast.json").write_text(
        json.dumps({"characters": [{"name": "the Time Traveller"}, {"name": "Weena"}]}),
        encoding="utf-8",
    )
    job = Job(id="b", book_id="b", state=state, started=True)
    job.save(cfg)
    return job


def _recording_handler(calls: list[dict[str, Any]], *, fail: set[str] | None = None):
    """A scene-update handler that records the posted ``prior_ledger`` and returns fixtures.

    ``fail`` names page ids that respond 422 (permanent unit failure) instead of a ledger.
    """
    fail = fail or set()

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        pid = body["text"].split()[-1]  # "PAGE 0003" -> "0003"
        calls.append({"pid": pid, "prior": body["options"]["prior_ledger"]})
        if pid in fail:
            return httpx.Response(422, json={"error": {"code": "validation_failed",
                                                       "detail": {"reasons": ["bad page"]}}})
        return httpx.Response(200, json=_scene_envelope(pid))

    return handler


def _drive(cfg: Config, runner: Runner, *, stop_states: set[str], max_ticks: int = 16) -> Job:
    for _ in range(max_ticks):
        asyncio.run(runner.tick())
        job = jobmod.load(cfg, "b")
        if job.state in stop_states:
            return job
    return jobmod.load(cfg, "b")


def _page_ledger(cfg: Config, pid: str) -> dict[str, Any]:
    page = json.loads((cfg.work_dir / "b" / "pages" / f"{pid}.json").read_text("utf-8"))
    return page["ledger"]


# --- threading (the load-bearing property) ---------------------------------


@respx.mock
def test_threading_prior_ledger_is_previous_output(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _seed_job(cfg)
    calls: list[dict[str, Any]] = []
    respx.post(_SCENE_URL).mock(side_effect=_recording_handler(calls))

    job = _drive(cfg, _runner(cfg), stop_states={JobState.LEDGER_DONE})
    assert job.state == JobState.LEDGER_DONE
    assert job.failed_units == []

    # Exactly one call per page, in strict order.
    assert [c["pid"] for c in calls] == _PAGE_IDS
    # Page 1 gets null; every later call is fed the previous page's returned ledger.
    assert calls[0]["prior"] is None
    for i in range(1, len(_PAGE_IDS)):
        assert calls[i]["prior"] == _ledger_fixture(_PAGE_IDS[i - 1])


# --- final merge writes ledgers into pages, schema-valid --------------------


@respx.mock
def test_merge_writes_schema_valid_page_ledgers(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _seed_job(cfg)
    respx.post(_SCENE_URL).mock(side_effect=_recording_handler([]))

    job = _drive(cfg, _runner(cfg), stop_states={JobState.LEDGER_DONE})
    assert job.state == JobState.LEDGER_DONE

    for pid in _PAGE_IDS:
        page = json.loads((cfg.work_dir / "b" / "pages" / f"{pid}.json").read_text("utf-8"))
        assert "ledger" in page
        schemas.validate("page", page)
        assert page["ledger"] == _ledger_fixture(pid)  # verbatim, no gaps
    # A scene_changed:true ledger survives the round-trip. Per-page verbatim equality above
    # already proves fidelity; this asserts the True value appears somewhere in the sequence
    # (page-independent — which page turns the scene varies with the capture).
    assert any(_page_ledger(cfg, pid)["scene_changed"] is True for pid in _PAGE_IDS)


# --- contiguity resume: skip done ledgers, thread from stored predecessor ---


@respx.mock
def test_resume_skips_done_and_threads_from_stored_predecessor(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _seed_job(cfg, state=JobState.LEDGER_RUNNING)
    # Pre-write ledgers 0001..0003 (as if a prior run completed them).
    ldir = cfg.work_dir / "b" / "ledgers"
    ldir.mkdir(parents=True, exist_ok=True)
    for pid in ["0001", "0002", "0003"]:
        (ldir / f"{pid}.json").write_text(json.dumps(_ledger_fixture(pid)), encoding="utf-8")
    calls: list[dict[str, Any]] = []
    respx.post(_SCENE_URL).mock(side_effect=_recording_handler(calls))

    job = jobmod.load(cfg, "b")
    asyncio.run(_runner(cfg).advance_job(job))

    assert job.state == JobState.LEDGER_DONE
    # Only the 3 missing pages were requested (contiguity: resume at the first gap).
    assert [c["pid"] for c in calls] == ["0004", "0005", "0006"]
    # Page 4 threads from the *stored* page-3 ledger.
    assert calls[0]["prior"] == _ledger_fixture("0003")


# --- gap rule: permanently-failed page inherits predecessor at phase end ----


@respx.mock
def test_gap_rule_inherits_predecessor_and_annotates(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _seed_job(cfg)
    calls: list[dict[str, Any]] = []
    respx.post(_SCENE_URL).mock(side_effect=_recording_handler(calls, fail={"0003"}))

    job = _drive(cfg, _runner(cfg), stop_states={JobState.LEDGER_DONE})

    # Phase completes despite the failed unit; page 3 is recorded as failed.
    assert job.state == JobState.LEDGER_DONE
    failed = [f for f in job.failed_units if f["unit"] == "0003"]
    assert failed and failed[0]["phase"] == "p3_ledger"

    # Merged page-3 ledger = a copy of page 2's + the gap annotation.
    l2, l3 = _page_ledger(cfg, "0002"), _page_ledger(cfg, "0003")
    assert l3["location"] == l2["location"]
    assert l3["carry_notes"].startswith(l2["carry_notes"])
    assert l3["carry_notes"].endswith(" [ledger gap]")

    # Pages 4–6 carry their real ledgers (not inherited).
    for pid in ["0004", "0005", "0006"]:
        assert _page_ledger(cfg, pid) == _ledger_fixture(pid)

    # During *generation*, page 4 threaded from the last *successful* ledger (page 2),
    # never from page 3's inherited gap ledger.
    page4_call = next(c for c in calls if c["pid"] == "0004")
    assert page4_call["prior"] == _ledger_fixture("0002")


# --- empty page: neutral ledger, no transform call (ADR-0017 safety net) -----


@respx.mock
def test_empty_page_gets_neutral_ledger_without_a_transform_call(tmp_path) -> None:
    # A blank OR near-empty page (e.g. a stray section-divider line that survived ingest) must
    # not be sent to the model: it would hallucinate a beat + salience that later gets
    # illustrated. It gets a neutral ledger (salience 0.0, empty beat) so selection can never
    # pick it. Uses a 2-word divider line to exercise the near-empty backstop (ADR-0018), not
    # just fully-empty text.
    cfg = _cfg(tmp_path)
    _seed_job(cfg)
    p3 = cfg.work_dir / "b" / "pages" / "0003.json"
    page = json.loads(p3.read_text("utf-8"))
    page["text"], page["word_count"] = "Book II", 2
    p3.write_text(json.dumps(page), encoding="utf-8")

    calls: list[dict[str, Any]] = []
    respx.post(_SCENE_URL).mock(side_effect=_recording_handler(calls))

    job = _drive(cfg, _runner(cfg), stop_states={JobState.LEDGER_DONE})
    assert job.state == JobState.LEDGER_DONE

    # No transform was issued for the blank page.
    assert "0003" not in [c["pid"] for c in calls]
    # Its ledger is neutral: zero salience, empty beat → never illustrated.
    l3 = _page_ledger(cfg, "0003")
    assert l3["visual_salience"] == 0.0
    assert l3["best_visual_beat"] == ""
    # The non-blank pages were still processed normally.
    assert {"0001", "0002", "0004", "0005", "0006"} <= {c["pid"] for c in calls}


# --- waiting_gpu: scene-update 503 parks on ledger_running then resumes ------


@respx.mock
def test_scene_update_503_parks_waiting_gpu_then_resumes(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _seed_job(cfg)
    state = {"down": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["down"]:
            return httpx.Response(503, json={"error": {"code": "busy"}})
        pid = json.loads(request.content)["text"].split()[-1]
        return httpx.Response(200, json=_scene_envelope(pid))

    respx.post(_SCENE_URL).mock(side_effect=handler)
    runner = _runner(cfg)

    parked = _drive(cfg, runner, stop_states={JobState.WAITING_GPU})
    assert parked.state == JobState.WAITING_GPU
    assert parked.prev_state == JobState.LEDGER_RUNNING

    state["down"] = False  # GPU back
    done = _drive(cfg, runner, stop_states={JobState.LEDGER_DONE})
    assert done.state == JobState.LEDGER_DONE
    assert done.failed_units == []
