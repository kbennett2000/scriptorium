"""P0→P8 end-to-end regression anchor (BUILD-PLAN S8/S10 acceptance).

Runs the whole bake — real P0 (ingest + paginate + persist) on a committed inline synthetic book,
then the registered :data:`BAKE_PIPELINE` through the real runner with respx standing in for every
TTS transform and :class:`FakeImagegen` for pixels — and asserts that **every schema-bound artifact
validates** at each resting point (``prompts_draft``, ``rendered``, ``published``). The shared
driver lives in :mod:`_pipeline_build` (also used by ``tools/make_fixture_bundle.py``).

This is the pipeline's standing regression guard: any later cycle that breaks a phase's artifact
contract fails here. TTS responses are generic-but-schema-valid (never keyed to page text), so the
test is independent of the hand-written per-page fixtures. Per CLAUDE.md it asserts schema/shape
only — never exact LLM/image content.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import respx
from verify_bundle import verify_bundle  # tools/ on path via conftest

import _pipeline_build as pb  # sibling harness (tests/ on path via conftest)
from scriptorium import schemas
from scriptorium.bake import job as jobmod
from scriptorium.bake.api import BakeBody, CreateBookBody, SourceBody, run_p0
from scriptorium.bake.job import JobState
from scriptorium.bake.runner import Runner
from scriptorium.config import Config


def _cfg(tmp_path) -> Config:
    return pb.make_cfg(tmp_path)


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

    body = CreateBookBody(
        source=SourceBody(kind="text", text=pb.SOURCE_TEXT, filename="synthetic.txt",
                          title="The Winter Quay", author="A. Fixture"),
        bake=BakeBody(style_id="engraving", density_preset="classic",
                      era="an imagined coastal town", portraits_enabled=True,
                      title="The Winter Quay", author="A. Fixture"),
    )
    job = run_p0(cfg, body)
    book_id = job.book_id
    assert job.state == JobState.INGESTED
    schemas.validate("structure", json.loads(
        (cfg.work_dir / book_id / "structure.json").read_text("utf-8")))
    n_pages = len(list((cfg.work_dir / book_id / "pages").glob("*.json")))
    assert 1 <= n_pages < 8  # a small book → P4 tiny-work

    job.started = True
    job.save(cfg)
    pb.register_tts_mocks()
    runner = Runner(cfg, pb.offline_pipeline(), sleep=pb._noop_sleep, wake=lambda _c: None,
                    gpu_gate=pb._gate_up)

    # Cast-review gate (ADR-0032): the runner rests at cast_done; approve to let P3→P5 run.
    pb._pump(runner, cfg, book_id, JobState.CAST_DONE)
    pb._approve_cast(cfg, book_id)
    for _ in range(40):
        asyncio.run(runner.tick())
        job = jobmod.load(cfg, book_id)
        if job.state in (JobState.PROMPTS_DRAFT, JobState.FAILED):
            break
    assert job.state == JobState.PROMPTS_DRAFT, f"stuck at {job.state}"

    counts = _validate_tree(cfg, book_id)
    assert counts["structure"] == 1
    assert counts["cast"] == 1
    assert counts["selection"] == 1
    assert counts["page"] == n_pages
    selection = json.loads((cfg.work_dir / book_id / "selection.json").read_text("utf-8"))
    n_selected = sum(1 for p in selection["plates"] if p["status"] == "selected")
    assert (cfg.work_dir / book_id / "prompts" / "cover.json").is_file()
    assert counts["prompt"] >= n_selected + 1  # pages + cover

    for p in (cfg.work_dir / book_id / "pages").glob("*.json"):
        assert "ledger" in json.loads(p.read_text("utf-8"))
    cover = json.loads((cfg.work_dir / book_id / "prompts" / "cover.json").read_text("utf-8"))
    assert cover["page_id"] == "cover"
    assert "frontispiece for the book 'The Winter Quay' by A. Fixture" in \
        cover["final_subject_prompt"]


@respx.mock
def test_p0_to_p7_renders_a_valid_bundle(tmp_path) -> None:
    """S10a anchor: P0→P7 with FakeImagegen reaches rendered, all work artifacts valid."""
    cfg = _cfg(tmp_path)
    body = CreateBookBody(
        source=SourceBody(kind="text", text=pb.SOURCE_TEXT, filename="synthetic.txt",
                          title="The Winter Quay", author="A. Fixture"),
        bake=BakeBody(style_id="engraving", density_preset="classic",
                      era="an imagined coastal town", portraits_enabled=True,
                      title="The Winter Quay", author="A. Fixture"),
    )
    job = run_p0(cfg, body)
    book_id = job.book_id
    job.started = True
    job.save(cfg)
    pb.register_tts_mocks()
    runner = Runner(cfg, pb.offline_pipeline(), sleep=pb._noop_sleep, wake=lambda _c: None,
                    gpu_gate=pb._gate_up)

    # Cast-review gate (ADR-0032): the runner rests at cast_done; approve to let P3→P5 run.
    pb._pump(runner, cfg, book_id, JobState.CAST_DONE)
    pb._approve_cast(cfg, book_id)
    for _ in range(40):
        asyncio.run(runner.tick())
        job = jobmod.load(cfg, book_id)
        if job.state in (JobState.PROMPTS_DRAFT, JobState.FAILED):
            break
    assert job.state == JobState.PROMPTS_DRAFT, f"stuck at {job.state}"

    pb._approve(cfg, book_id)
    for _ in range(40):
        asyncio.run(runner.tick())
        job = jobmod.load(cfg, book_id)
        if job.state in (JobState.RENDERED, JobState.FAILED):
            break
    assert job.state == JobState.RENDERED, f"stuck at {job.state}"

    counts = _validate_tree(cfg, book_id)
    assert counts["prompt"] >= 2  # at least a page plate + cover

    book = cfg.work_dir / book_id
    sel = json.loads((book / "selection.json").read_text("utf-8"))
    approved_pages = [p["page_id"] for p in sel["plates"]]
    assert approved_pages, "expected at least one plate"
    for pid in approved_pages:
        assert (book / "images" / "plates" / f"{pid}.png").is_file(), pid
        assert (book / "images" / "web" / "plates" / f"{pid}.webp").is_file(), pid
        assert (book / "images" / "thumbs" / "plates" / f"{pid}.webp").is_file(), pid
        assert {p["page_id"]: p["status"] for p in sel["plates"]}[pid] == "rendered"
        doc = json.loads((book / "prompts" / f"{pid}.json").read_text("utf-8"))
        assert doc["wrapped_prompt"] and doc["negative_prompt"]
        assert doc["render"]["attempts"] == 1

    assert (book / "images" / "cover.png").is_file()
    assert (book / "images" / "web" / "cover.webp").is_file()


def test_p0_to_p8_publishes_a_verifiable_bundle(tmp_path) -> None:
    """S10b anchor: the whole bake reaches ``published`` and ``verify_bundle`` finds no problems."""
    cfg = _cfg(tmp_path)
    book_id = pb.build_to_published(cfg, freeze=False)

    library = cfg.library_dir / book_id
    assert (library / "manifest.json").is_file()
    assert (library / "meta.json").is_file()
    # meta + manifest validate; the bundle is internally consistent per the standalone verifier.
    schemas.validate("meta", json.loads((library / "meta.json").read_text("utf-8")))
    schemas.validate("manifest", json.loads((library / "manifest.json").read_text("utf-8")))
    assert verify_bundle(library) == []

    # Work-tree sidecars never leak into the published bundle (a derivative-idempotency aid only).
    assert not any(p.name.endswith(".src.sha256") for p in library.rglob("*"))
    # The raw ledgers dir is not published (its merged form rides on pages/*).
    assert not (library / "ledgers").exists()
