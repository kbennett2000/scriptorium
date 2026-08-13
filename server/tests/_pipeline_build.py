"""Shared offline P0→P8 bundle builder (used by test_pipeline_e2e + tools/make_fixture_bundle).

Drives the *real* bake pipeline — real P0 (ingest + paginate) then the registered phases through the
real runner — with respx standing in for every TTS transform and :class:`FakeImagegen`
(deterministic placeholder pixels) standing in for the GPU render. The result is a genuine published
``library/{id}`` bundle produced by the same P8 code that runs in production, GPU-less.

Determinism: the synthetic source paginates identically every run, the TTS mocks are fixed,
FakeImagegen burns the request hash into stable pixels, and this harness **freezes the clock**
(``_now_iso``) and **pins ``meta.bake``** to fixed values — so ``make_fixture_bundle`` re-emits the
committed bundle byte-for-byte (``git diff --exit-code``). The e2e test asserts schema/shape only,
so the frozen values never leak into content assertions (CLAUDE.md).
"""

from __future__ import annotations

import asyncio
import json
import shutil
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import httpx
import respx

from scriptorium.app import BAKE_PIPELINE
from scriptorium.bake import job as jobmod
from scriptorium.bake.api import BakeBody, CreateBookBody, SourceBody, run_p0
from scriptorium.bake.job import JobState
from scriptorium.bake.phases import p7_render, p8_publish
from scriptorium.bake.phases.p7_render import PortraitRender, Render
from scriptorium.bake.runner import Runner
from scriptorium.config import Config
from scriptorium.render.imagegen import FakeImagegen

TTS = "http://tts.test:8712"
# The frozen clock (a valid RFC-3339 date-time; jsonschema doesn't enforce format but keep it real).
FIXED_TS = "2026-07-13T00:00:00+00:00"

# A deterministic synthetic book: enough plain prose to paginate to a small (< 8-page) book so P4
# uses its tiny-work path and the fixture stays compact.
_PARAGRAPH = (
    "The quiet harbour lay under a cold grey sky as the wanderer walked the length of the "
    "stone quay past shuttered stalls and coiled ropes and the salt smell of the turning tide. "
)
SOURCE_TEXT = ("\n\n".join(_PARAGRAPH for _ in range(90))).strip()

# Generic, schema-valid TTS responses — never keyed to page text (so the harness is independent of
# the paginator's exact output and of the hand-written per-page fixtures).
GENERIC_MENTIONS = {
    "output": {"mentions": [
        {"name": "the Wanderer", "aliases": ["the traveller"],
         "descriptors": ["a weathered solitary figure in a long coat"], "is_person": True},
    ]},
    "meta": {},
}
GENERIC_CANON = {
    "output": {
        "visual_description": "a weathered solitary figure in a long grey coat, hood drawn up",
        "one_line": "A traveller who walks the winter quay",
        "tags": ["traveller", "solitary"],
    },
    "meta": {},
}
GENERIC_PROMPT = {
    "output": {
        "prompt": "a solitary hooded figure walking a cold stone harbour quay beneath a wide "
                  "grey sky, shuttered stalls and coiled ropes along the wet stone",
        "depicted": ["the Wanderer"], "shot": "wide", "avoid": ["color", "modern dress"],
    },
    "meta": {"transform": "illustration-prompt", "attempts": 1},
}

# A fixed bake-provenance block so meta.json is reproducible (real pinning is best-effort + live).
FIXED_BAKE = {
    "completed_at": FIXED_TS,
    "transform_service": {"url_host": "tts.test:8712", "transforms": {
        "cast-mentions": "0.0.0-fixture", "cast-canonicalize": "0.0.0-fixture",
        "scene-update": "0.0.0-fixture", "illustration-prompt": "0.0.0-fixture"}},
    "models": {"llm": "fixture-llm", "imagegen": "fixture-imagegen"},
    "pipeline_version": "S10b-fixture",
}


def scene_handler(counter: list[int]):
    """Generic scene-update: a valid ledger with rising salience so P4 has a clear argmax."""
    def handler(request: httpx.Request) -> httpx.Response:
        counter[0] += 1
        return httpx.Response(200, json={"output": {
            "location": "the stone quay", "time_of_day": "day", "atmosphere": "cold, grey",
            "present": ["the Wanderer"], "scene_changed": counter[0] == 2,
            "visual_salience": round(0.40 + 0.05 * counter[0], 2),
            "best_visual_beat": "a lone figure on the empty quay", "carry_notes": "",
        }, "meta": {}})
    return handler


def register_tts_mocks() -> None:
    """Register the generic schema-valid TTS transform mocks (+ the P7 unload) on active respx."""
    respx.post(f"{TTS}/v1/transform/cast-mentions").mock(
        return_value=httpx.Response(200, json=GENERIC_MENTIONS))
    respx.post(f"{TTS}/v1/transform/cast-canonicalize").mock(
        return_value=httpx.Response(200, json=GENERIC_CANON))
    respx.post(f"{TTS}/v1/transform/scene-update").mock(side_effect=scene_handler([0]))
    respx.post(f"{TTS}/v1/transform/illustration-prompt").mock(
        return_value=httpx.Response(200, json=GENERIC_PROMPT))
    respx.post(f"{TTS}/v1/models/unload").mock(return_value=httpx.Response(200, json={}))


def offline_pipeline() -> list:
    """The registered pipeline with both render phases swapped for FakeImagegen (no GPU).

    Both the portrait render (ADR-0025) and the page render are GPU phases; swap each for a
    FakeImagegen-backed instance so the offline P0→P8 build never touches a real imagegen client.
    """
    fake = FakeImagegen()
    render_names = {"p7_render", "portrait_render"}
    pipeline = [p for p in BAKE_PIPELINE if getattr(p, "name", None) not in render_names]
    pipeline.append(PortraitRender(client=fake))
    pipeline.append(Render(client=fake))
    return pipeline


def make_cfg(data_dir: Path) -> Config:
    """A Config rooted at ``data_dir`` with a mocked TTS URL and no imagegen (FakeImagegen only)."""
    return Config(
        data_dir=data_dir, port=8720, tts_url=TTS, imagegen_url=None, gpu_mac=None,
        gpu_wol_enabled=False, runner_tick_s=1, shared_dir=data_dir,
    )


async def _gate_up(_cfg: Config) -> bool:
    return True


async def _noop_sleep(_s: float) -> None:
    return None


def build_to_published(cfg: Config, *, freeze: bool = True) -> str:
    """Run the real P0→P8 pipeline offline and return the published book_id.

    ``freeze`` (default) pins the clock + ``meta.bake`` so the output is byte-reproducible; the e2e
    test can leave it on (it asserts shape only). Registers its own respx mocks + patches.
    """
    body = CreateBookBody(
        source=SourceBody(kind="text", text=SOURCE_TEXT, filename="synthetic.txt",
                          title="The Winter Quay", author="A. Fixture"),
        bake=BakeBody(style_id="engraving", density_preset="classic",
                      era="an imagined coastal town", portraits_enabled=True,
                      title="The Winter Quay", author="A. Fixture"),
    )
    with ExitStack() as stack:
        stack.enter_context(respx.mock)
        if freeze:
            stack.enter_context(mock.patch.object(p7_render, "_now_iso", lambda: FIXED_TS))
            stack.enter_context(mock.patch.object(p8_publish, "_now_iso", lambda: FIXED_TS))
            stack.enter_context(
                mock.patch.object(p8_publish, "_pin_bake", lambda _c: dict(FIXED_BAKE)))
        register_tts_mocks()

        job = run_p0(cfg, body)
        book_id = job.book_id
        if freeze:
            job.created_at = FIXED_TS  # meta.source.retrieved_at
        job.started = True
        job.save(cfg)

        runner = Runner(cfg, offline_pipeline(), sleep=_noop_sleep, wake=lambda _c: None,
                        gpu_gate=_gate_up)
        # P1→P2 to the cast gate, approve cast, P3→P5 to prompts_draft, approve, then render.
        _pump(runner, cfg, book_id, JobState.CAST_DONE)
        _approve_cast(cfg, book_id)
        _pump(runner, cfg, book_id, JobState.PROMPTS_DRAFT)
        _approve(cfg, book_id)
        _pump(runner, cfg, book_id, JobState.PUBLISHED)
    return book_id


def _pump(runner: Runner, cfg: Config, book_id: str, target: str) -> None:
    for _ in range(60):
        asyncio.run(runner.tick())
        job = jobmod.load(cfg, book_id)
        if job.state in (target, JobState.FAILED):
            break
    job = jobmod.load(cfg, book_id)
    if job.state != target:
        raise RuntimeError(f"pipeline stuck at {job.state}, expected {target}")


def _approve_cast(cfg: Config, book_id: str) -> None:
    """Mimic the cast-review gate approve (ADR-0032): job ``cast_done → cast_approved``."""
    job = jobmod.load(cfg, book_id)
    job.transition(JobState.CAST_APPROVED)
    job.save(cfg)


def _approve(cfg: Config, book_id: str) -> None:
    """Mimic the review gate's approve: selected plates → approved, job → approved."""
    sel_path = cfg.work_dir / book_id / "selection.json"
    sel = json.loads(sel_path.read_text("utf-8"))
    for plate in sel["plates"]:
        if plate["status"] == "selected":
            plate["status"] = "approved"
    sel_path.write_text(json.dumps(sel), encoding="utf-8")
    job = jobmod.load(cfg, book_id)
    job.transition(JobState.IN_REVIEW)
    job.transition(JobState.APPROVED)
    job.save(cfg)


def build_fixture_bundle(out_dir: Path, work_root: Path) -> dict:
    """Build a fresh published bundle under a temp ``work_root`` and copy it to ``out_dir``.

    Returns a small summary. ``out_dir`` is replaced wholesale so no stale files linger.
    """
    cfg = make_cfg(work_root)
    book_id = build_to_published(cfg, freeze=True)
    src = cfg.library_dir / book_id
    if out_dir.exists():
        shutil.rmtree(out_dir)
    shutil.copytree(src, out_dir)
    manifest = json.loads((out_dir / "manifest.json").read_text("utf-8"))
    return {"book_id": book_id, "files": len(manifest["files"]), "out": str(out_dir)}
