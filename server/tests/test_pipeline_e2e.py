"""P0→P5 end-to-end regression anchor (BUILD-PLAN S8 acceptance).

Runs the whole bake — real P0 (ingest + paginate + persist) via ``run_p0`` on a committed inline
synthetic book, then the registered :data:`BAKE_PIPELINE` (P1→P5) through the real runner with
respx standing in for every TTS transform — and asserts that **every schema-bound artifact in the
work dir validates**: ``structure.json``, every ``pages/*.json`` (with its merged ledger),
``cast.json``, ``selection.json``, and every ``prompts/*.json`` (pages + cover + portraits).

This is the pipeline's standing regression guard: any later cycle that breaks a phase's artifact
contract fails here. TTS responses are generic-but-schema-valid (never keyed to page text), so the
test is independent of the hand-written per-page fixtures and of what the paginator emits. Per
CLAUDE.md it asserts schema/shape only — never exact LLM content.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import respx

from scriptorium import schemas
from scriptorium.app import BAKE_PIPELINE
from scriptorium.bake import job as jobmod
from scriptorium.bake.api import BakeBody, CreateBookBody, SourceBody, run_p0
from scriptorium.bake.job import JobState
from scriptorium.bake.runner import Runner
from scriptorium.config import Config

TTS = "http://tts.test:8712"


def _cfg(tmp_path) -> Config:
    return Config(
        data_dir=tmp_path, port=8720, tts_url=TTS, imagegen_url=None, gpu_mac=None,
        gpu_wol_enabled=False, runner_tick_s=1, shared_dir=tmp_path,
    )


async def _gate_up(_cfg: Config) -> bool:
    return True


async def _noop_sleep(_s: float) -> None:
    return None


# Enough plain prose to paginate into a synthetic ~6-page book (< 8, so P4 uses tiny-work).
_PARAGRAPH = (
    "The quiet harbour lay under a cold grey sky as the wanderer walked the length of the "
    "stone quay past shuttered stalls and coiled ropes and the salt smell of the turning tide. "
)
_SOURCE_TEXT = ("\n\n".join(_PARAGRAPH for _ in range(90))).strip()

_GENERIC_MENTIONS = {
    "output": {"mentions": [
        {"name": "the Wanderer", "aliases": ["the traveller"],
         "descriptors": ["a weathered solitary figure in a long coat"], "is_person": True},
    ]},
    "meta": {},
}
_GENERIC_CANON = {
    "output": {
        "visual_description": "a weathered solitary figure in a long grey coat, hood drawn up",
        "one_line": "A traveller who walks the winter quay",
        "tags": ["traveller", "solitary"],
    },
    "meta": {},
}
_GENERIC_PROMPT = {
    "output": {
        "prompt": "a solitary hooded figure walking a cold stone harbour quay beneath a wide "
                  "grey sky, shuttered stalls and coiled ropes along the wet stone",
        "depicted": ["the Wanderer"], "shot": "wide", "avoid": ["color", "modern dress"],
    },
    "meta": {"transform": "illustration-prompt", "attempts": 1},
}


def _scene_handler(counter: list[int]):
    """Generic scene-update: a valid ledger with a rising salience so P4 has a clear argmax."""
    def handler(request: httpx.Request) -> httpx.Response:
        counter[0] += 1
        return httpx.Response(200, json={"output": {
            "location": "the stone quay", "time_of_day": "day", "atmosphere": "cold, grey",
            "present": ["the Wanderer"], "scene_changed": counter[0] == 2,
            "visual_salience": round(0.40 + 0.05 * counter[0], 2),
            "best_visual_beat": "a lone figure on the empty quay", "carry_notes": "",
        }, "meta": {}})
    return handler


def _validate_tree(cfg: Config, book_id: str) -> dict[str, int]:
    """Validate every schema-bound artifact in ``work/{book_id}/`` and return a count per kind."""
    book = cfg.work_dir / book_id
    counts = {"page": 0, "structure": 0, "cast": 0, "selection": 0, "prompt": 0}

    def _check(kind: str, path: Path) -> None:
        schemas.validate(kind, json.loads(path.read_text("utf-8")))
        counts[kind] += 1

    _check("structure", book / "structure.json")
    _check("cast", book / "cast.json")
    _check("selection", book / "selection.json")
    for p in sorted((book / "pages").glob("*.json")):
        _check("page", p)
    for p in sorted((book / "prompts").glob("*.json")):
        _check("prompt", p)
    return counts


@respx.mock
def test_p0_to_p5_produces_all_valid_artifacts(tmp_path) -> None:
    cfg = _cfg(tmp_path)

    # P0: ingest + paginate + persist a real work dir (pages + structure), job at ``ingested``.
    body = CreateBookBody(
        source=SourceBody(kind="text", text=_SOURCE_TEXT, filename="synthetic.txt",
                          title="The Winter Quay", author="A. Fixture"),
        bake=BakeBody(style_id="engraving", density_preset="classic",
                      era="an imagined coastal town", portraits_enabled=True,
                      title="The Winter Quay", author="A. Fixture"),
    )
    job = run_p0(cfg, body)
    book_id = job.book_id
    assert job.state == JobState.INGESTED
    # P0 artifacts already validate.
    schemas.validate("structure", json.loads(
        (cfg.work_dir / book_id / "structure.json").read_text("utf-8")))
    n_pages = len(list((cfg.work_dir / book_id / "pages").glob("*.json")))
    assert 1 <= n_pages < 8  # a small book → P4 tiny-work

    # Start the job and stub every TTS transform with generic schema-valid responses.
    job.started = True
    job.save(cfg)
    respx.post(f"{TTS}/v1/transform/cast-mentions").mock(
        return_value=httpx.Response(200, json=_GENERIC_MENTIONS))
    respx.post(f"{TTS}/v1/transform/cast-canonicalize").mock(
        return_value=httpx.Response(200, json=_GENERIC_CANON))
    respx.post(f"{TTS}/v1/transform/scene-update").mock(side_effect=_scene_handler([0]))
    respx.post(f"{TTS}/v1/transform/illustration-prompt").mock(
        return_value=httpx.Response(200, json=_GENERIC_PROMPT))

    runner = Runner(cfg, BAKE_PIPELINE, sleep=_noop_sleep, wake=lambda _c: None,
                    gpu_gate=_gate_up)

    # P1→P5: pump the runner until the job reaches prompts_draft (one phase per tick).
    for _ in range(40):
        asyncio.run(runner.tick())
        job = jobmod.load(cfg, book_id)
        if job.state in (JobState.PROMPTS_DRAFT, JobState.FAILED):
            break
    assert job.state == JobState.PROMPTS_DRAFT, f"stuck at {job.state}"

    # The acceptance box: every schema-bound artifact in the work dir validates.
    counts = _validate_tree(cfg, book_id)
    assert counts["structure"] == 1
    assert counts["cast"] == 1
    assert counts["selection"] == 1
    assert counts["page"] == n_pages
    # One prompt per selected page + the cover pseudo-plate (+ any portraits).
    selection = json.loads((cfg.work_dir / book_id / "selection.json").read_text("utf-8"))
    n_selected = sum(1 for p in selection["plates"] if p["status"] == "selected")
    assert (cfg.work_dir / book_id / "prompts" / "cover.json").is_file()
    assert counts["prompt"] >= n_selected + 1  # pages + cover

    # Every merged page carries a ledger (P3), and the cover prompt reflects the §10 formula.
    for p in (cfg.work_dir / book_id / "pages").glob("*.json"):
        assert "ledger" in json.loads(p.read_text("utf-8"))
    cover = json.loads((cfg.work_dir / book_id / "prompts" / "cover.json").read_text("utf-8"))
    assert cover["page_id"] == "cover"
    assert "frontispiece for the book 'The Winter Quay' by A. Fixture" in \
        cover["final_subject_prompt"]
