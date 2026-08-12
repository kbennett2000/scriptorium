"""Picture-set render phase (DESIGN §8, ADR-0014) — Phase 2 acceptance.

Drives the real Runner over ``[SetRender(FakeImagegen())]`` from ``set_rendering`` (TTS unload
mocked by respx) against a seeded **published** book, and asserts: the set dir gets a web image per
page plate + cover + portrait, a schema-valid manifest, ``set.json`` flips to ``ready``; the set's
style is applied (prefix in provenance); a re-roll's seed differs (set_id folded); and — the
invariant — ``library/{book}`` and the book's own job/work tree are byte-untouched. Image *content*
is never asserted, only shape/paths/provenance (CLAUDE.md).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import httpx
import respx

from scriptorium import schemas
from scriptorium.artsets import service
from scriptorium.artsets.phase import SetRender, set_render_progress
from scriptorium.bake import job as jobmod
from scriptorium.bake.job import JobState, can_transition
from scriptorium.bake.phases.p7_render import _asset_spec
from scriptorium.bake.runner import Runner
from scriptorium.config import Config
from scriptorium.render.imagegen import FakeImagegen
from scriptorium.styles import get_style

TTS = "http://tts.test:8712"
BOOK = "usr-abc123def456"


def _cfg(tmp_path) -> Config:
    repo_shared = Path(__file__).resolve().parents[2] / "shared"
    return Config(
        data_dir=tmp_path, port=8720, tts_url=TTS, imagegen_url=None, gpu_mac=None,
        gpu_wol_enabled=False, runner_tick_s=1, shared_dir=repo_shared,
    )


async def _noop_sleep(_s: float) -> None:
    return None


async def _gate_up(_cfg: Config) -> bool:
    return True


def _prompt_doc(page_id: str, prompt: str, avoid=None) -> dict:
    derived = {"prompt": prompt}
    if avoid is not None:
        derived["avoid"] = avoid
    return {"page_id": page_id, "derived": derived,
            "edited_prompt": None, "final_subject_prompt": prompt}


def _seed_library(cfg: Config, *, book: str = BOOK, style_id: str = "comic-book") -> None:
    """A published book with two page plates + one major character, in ``style_id``."""
    lib = cfg.library_dir / book
    (lib / "prompts").mkdir(parents=True, exist_ok=True)
    (lib / "pages").mkdir(parents=True, exist_ok=True)
    for pid, text, avoid in [("0001", "a lamplit workshop", ["modern dress"]),
                             ("0003", "a clock tower at dusk", None)]:
        (lib / "prompts" / f"{pid}.json").write_text(
            json.dumps(_prompt_doc(pid, text, avoid)), encoding="utf-8")
    for pid, seq, sal, beat in [("0001", 1, 0.9, "a lamplit workshop at dawn"),
                                ("0003", 3, 0.5, "")]:
        (lib / "pages" / f"{pid}.json").write_text(json.dumps({
            "id": pid, "seq": seq, "chapter": 1, "text": "Some prose.", "word_count": 2,
            "ledger": {"location": "", "time_of_day": "unknown", "atmosphere": "", "present": [],
                       "scene_changed": False, "visual_salience": sal,
                       "best_visual_beat": beat, "carry_notes": ""},
        }), encoding="utf-8")
    (lib / "selection.json").write_text(json.dumps({
        "preset": "classic",
        "params": {"min_gap": 2, "max_gap": 6, "salience_floor": 0.55,
                   "chapter_open": True, "scene_boundary": True},
        "plates": [
            {"page_id": "0001", "reason": "chapter_open", "salience": 0.8,
             "status": "rendered", "added_in_revision": 1},
            {"page_id": "0003", "reason": "fill", "salience": 0.6,
             "status": "rendered", "added_in_revision": 1},
        ],
    }), encoding="utf-8")
    (lib / "cast.json").write_text(json.dumps({"characters": [
        {"slug": "the-clockmaker", "name": "the Clockmaker", "aliases": [],
         "mention_pages": ["0001"], "major": True,
         "visual_description": "an old man with brass goggles", "one_line": "A tinkerer of clocks",
         "tags": [], "portrait": None, "edited_by_human": False},
    ]}), encoding="utf-8")
    (lib / "meta.json").write_text(json.dumps({
        "book_id": book, "revision": 1, "title": "The Clock", "author": "A. Maker",
        "style_id": style_id,
    }), encoding="utf-8")


def _dir_digest(path: Path) -> dict[str, str]:
    if not path.is_dir():
        return {}
    return {
        str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(path.rglob("*")) if p.is_file()
    }


def _runner(cfg: Config, client) -> Runner:
    return Runner(cfg, [SetRender(client=client)],
                  sleep=_noop_sleep, wake=lambda _c: None, gpu_gate=_gate_up)


def _drive(cfg: Config, client, job_id: str, *, max_ticks: int = 16,
           until=(JobState.SET_DONE, JobState.FAILED, JobState.WAITING_GPU)):
    runner = _runner(cfg, client)
    for _ in range(max_ticks):
        asyncio.run(runner.tick())
        job = jobmod.load(cfg, job_id)
        if job.state in until:
            return job
    return jobmod.load(cfg, job_id)


def _set_dir(cfg: Config, user: str, book: str, set_id: str) -> Path:
    return cfg.artsets_dir / user / book / set_id


@respx.mock
def test_set_render_produces_web_images_manifest_and_ready(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _seed_library(cfg)
    respx.post(f"{TTS}/v1/models/unload").mock(return_value=httpx.Response(200, json={}))

    set_doc = service.create_set(cfg, "kris", BOOK, "style", "engraving", None)
    set_id = set_doc["set_id"]
    job = _drive(cfg, FakeImagegen(), service.set_job_id(BOOK, set_id))
    assert job.state == JobState.SET_DONE, f"stuck at {job.state}"

    sd = _set_dir(cfg, "kris", BOOK, set_id)
    # A reader web image for each page plate + cover + the one major character's portrait.
    for rel in ["images/web/plates/0001.webp", "images/web/plates/0003.webp",
                "images/web/cover.webp", "images/web/portraits/the-clockmaker.webp"]:
        assert (sd / rel).is_file(), f"missing {rel}"

    manifest = json.loads((sd / "manifest.json").read_text("utf-8"))
    schemas.validate("manifest", manifest)
    assert manifest["book_id"] == BOOK

    final = json.loads((sd / "set.json").read_text("utf-8"))
    assert final["status"] == "ready"

    # The set's style is applied: page plates + cover carry the style prefix; the portrait carries
    # the style's portrait prefix (mirrors P5/P7).
    style = get_style("engraving")
    for pid, expected in [("0001", style["prefix"]), ("cover", style["prefix"]),
                          ("portrait-the-clockmaker", style["portrait_prefix"])]:
        prov = json.loads((sd / "prompts" / f"{pid}.json").read_text("utf-8"))
        assert prov["wrapped_prompt"].startswith(expected)


@respx.mock
def test_reroll_seed_differs_from_another_set(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _seed_library(cfg)
    respx.post(f"{TTS}/v1/models/unload").mock(return_value=httpx.Response(200, json={}))

    a = service.create_set(cfg, "kris", BOOK, "style", "engraving", None)["set_id"]
    b = service.create_set(cfg, "kris", BOOK, "reroll", None, None)["set_id"]  # → book style
    _drive(cfg, FakeImagegen(), service.set_job_id(BOOK, a))
    _drive(cfg, FakeImagegen(), service.set_job_id(BOOK, b))

    def _seed(set_id: str) -> int:
        prov = _set_dir(cfg, "kris", BOOK, set_id) / "prompts" / "0001.json"
        return json.loads(prov.read_text("utf-8"))["seed"]

    assert _seed(a) != _seed(b)  # folding set_id makes each set's pixels distinct


@respx.mock
def test_set_render_never_touches_the_published_book(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _seed_library(cfg)
    respx.post(f"{TTS}/v1/models/unload").mock(return_value=httpx.Response(200, json={}))
    lib = cfg.library_dir / BOOK
    before = _dir_digest(lib)

    set_id = service.create_set(cfg, "kris", BOOK, "style", "engraving", None)["set_id"]
    _drive(cfg, FakeImagegen(), service.set_job_id(BOOK, set_id))
    service.delete_set(cfg, "kris", BOOK, set_id)

    assert _dir_digest(lib) == before  # library byte-identical across create + render + delete
    assert not (cfg.work_dir / BOOK).exists()  # no work tree for the book
    assert not jobmod.job_path(cfg, BOOK).exists()  # the book's own job id untouched
    assert not _set_dir(cfg, "kris", BOOK, set_id).exists()  # the set subtree is gone


def test_set_state_machine_edges() -> None:
    # The side lifecycle is wired (else the runner's park/fail handlers would raise inside their
    # own except and kill the worker), and it is NOT spliced into the book pipeline.
    assert can_transition(JobState.SET_RENDERING, JobState.SET_DONE)
    assert can_transition(JobState.SET_RENDERING, JobState.FAILED)
    assert can_transition(JobState.SET_RENDERING, JobState.WAITING_GPU)
    assert can_transition(JobState.WAITING_GPU, JobState.SET_RENDERING)
    assert not can_transition(JobState.SET_DONE, JobState.PUBLISHED)  # terminal
    assert not can_transition(JobState.SET_RENDERING, JobState.RENDERED)  # off the book chain


@respx.mock
def test_unload_failure_parks_then_resumes(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _seed_library(cfg)
    calls = {"n": 0}

    def _unload(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, json={}) if calls["n"] == 1 else httpx.Response(200, json={})

    respx.post(f"{TTS}/v1/models/unload").mock(side_effect=_unload)

    set_id = service.create_set(cfg, "kris", BOOK, "style", "engraving", None)["set_id"]
    job_id = service.set_job_id(BOOK, set_id)

    # First tick: unload 503 → GpuUnavailable → parked; nothing rendered yet.
    asyncio.run(_runner(cfg, FakeImagegen()).tick())
    assert jobmod.load(cfg, job_id).state == JobState.WAITING_GPU
    assert not (_set_dir(cfg, "kris", BOOK, set_id) / "images").exists()

    # Subsequent ticks resume to set_rendering and complete.
    job = _drive(cfg, FakeImagegen(), job_id)
    assert job.state == JobState.SET_DONE


# --- render progress (the reader's "Pictures" live status) -----------------
#
# The seeded book has 2 page plates (0001, 0003) + cover + 1 major portrait = 4 pictures.


@respx.mock
def test_list_reports_render_progress_while_generating(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _seed_library(cfg)
    set_id = service.create_set(cfg, "kris", BOOK, "style", "engraving", None)["set_id"]

    listing = service.list_sets(cfg, "kris", BOOK)
    schemas.validate("artset-list", listing)  # the new optional field stays schema-valid
    row = next(s for s in listing["sets"] if s["set_id"] == set_id)
    assert row["status"] == "generating"
    assert row["render_progress"] == {"done": 0, "total": 4}  # nothing rendered yet
    # The synthetic default set never carries progress.
    default = next(s for s in listing["sets"] if s["set_id"] == "default")
    assert "render_progress" not in default


def test_render_progress_counts_rendered_pictures(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _seed_library(cfg)
    set_id = service.create_set(cfg, "kris", BOOK, "style", "engraving", None)["set_id"]
    job = jobmod.load(cfg, service.set_job_id(BOOK, set_id))

    assert set_render_progress(cfg, job) == (0, 4)
    # A picture counts as done only once all three derivatives exist (mirrors SetRender.unit_done).
    spec = _asset_spec(_set_dir(cfg, "kris", BOOK, set_id), "0001")
    for p in (spec.src, spec.web, spec.thumb):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    assert set_render_progress(cfg, job) == (1, 4)


@respx.mock
def test_ready_and_failed_sets_carry_no_progress(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _seed_library(cfg)
    respx.post(f"{TTS}/v1/models/unload").mock(return_value=httpx.Response(200, json={}))

    ready_id = service.create_set(cfg, "kris", BOOK, "style", "engraving", None)["set_id"]
    _drive(cfg, FakeImagegen(), service.set_job_id(BOOK, ready_id))
    ready = next(s for s in service.list_sets(cfg, "kris", BOOK)["sets"] if s["set_id"] == ready_id)
    assert ready["status"] == "ready" and "render_progress" not in ready

    # A set whose job vanished reconciles to failed — and failed carries no progress.
    stalled_id = service.create_set(cfg, "kris", BOOK, "style", "engraving", None)["set_id"]
    jobmod.job_path(cfg, service.set_job_id(BOOK, stalled_id)).unlink()
    failed = next(
        s for s in service.list_sets(cfg, "kris", BOOK)["sets"] if s["set_id"] == stalled_id
    )
    assert failed["status"] == "failed" and "render_progress" not in failed


@respx.mock
def test_set_conditions_page_plates_on_its_own_portraits_and_anchors_the_era(tmp_path) -> None:
    """ADR-0026: a picture set is no longer rendered prompt-only.

    Before this, a set fed no ``references`` at all, so every re-illustration lost the character
    consistency the book's own render had — and it never saw the book's era, because a set job's
    bake_config carries only ``style_id``. Portraits must also render *before* the page plates so
    the reference file exists inside the set.
    """
    cfg = _cfg(tmp_path)
    _seed_library(cfg)
    lib = cfg.library_dir / BOOK
    meta = json.loads((lib / "meta.json").read_text())
    meta["era"] = "Russia 1870s"
    (lib / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    doc = json.loads((lib / "prompts" / "0001.json").read_text())
    doc["derived"]["depicted"] = ["the Clockmaker"]
    doc["derived"]["shot"] = "medium"
    (lib / "prompts" / "0001.json").write_text(json.dumps(doc), encoding="utf-8")
    respx.post(f"{TTS}/v1/models/unload").mock(return_value=httpx.Response(200, json={}))

    calls: list[tuple[str, object]] = []

    class _RefRecording(FakeImagegen):
        async def txt2img(self, *args, **kwargs) -> bytes:
            calls.append((args[0], kwargs.get("references")))
            return await super().txt2img(*args, **kwargs)

    set_id = service.create_set(cfg, "kris", BOOK, "style", "engraving", None)["set_id"]
    job = _drive(cfg, _RefRecording(), service.set_job_id(BOOK, set_id))
    assert job.state == JobState.SET_DONE, f"stuck at {job.state}"

    set_dir = _set_dir(cfg, "kris", BOOK, set_id)
    with_refs = [(p, r) for (p, r) in calls if r]
    assert len(with_refs) == 1, "exactly the one depicted page plate should carry a reference"
    prompt, refs = with_refs[0]
    # The reference is the portrait rendered into *this set*, not the book's.
    assert refs == [(set_dir / "images" / "portraits" / "the-clockmaker.png").read_bytes()]
    assert "Russia 1870s, a lamplit workshop" in prompt
    assert "medium shot" in prompt

    recorded = json.loads((set_dir / "prompts" / "0001.json").read_text())
    assert recorded["reference_slug"] == "the-clockmaker"
    assert json.loads((set_dir / "prompts" / "0003.json").read_text())["reference_slug"] is None
