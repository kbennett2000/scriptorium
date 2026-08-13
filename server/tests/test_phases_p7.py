"""P7 real render phase (DESIGN §10, §7.4; ADR-0009) — the S10a acceptance boxes.

Drives the real Runner over ``[RenderEnter(), Render(FakeImagegen())]`` from ``approved`` with TTS
``/v1/models/unload`` mocked by respx, and asserts the render contract: PNGs land at the §10 sizes,
WebP derivatives are produced, prompts gain ``wrapped_prompt``/``negative_prompt``/``render``
provenance, page plates flip to ``rendered``, the job rests at ``rendered``. Also covers the §7.4
ordering invariant (TTS unloaded before any imagegen call) and unload-failure parking on
``waiting_gpu``. Image *content* is never asserted — only sizes/validity (CLAUDE.md).
"""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path

import httpx
import respx
from PIL import Image

from scriptorium.bake import job as jobmod
from scriptorium.bake.job import Job, JobState
from scriptorium.bake.phases.p7_render import (
    PortraitRender,
    PortraitRenderEnter,
    Render,
    render_plate,
)
from scriptorium.bake.runner import Runner
from scriptorium.config import Config
from scriptorium.render.imagegen import FakeImagegen

TTS = "http://tts.test:8712"


def _cfg(tmp_path) -> Config:
    # shared_dir points at the real repo shared/ so schema validation works; styles come from the
    # repo's data/styles.json (default). tts_url is set so TtsClient can issue the unload call.
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


def _seed(cfg: Config, book_id: str = "b") -> None:
    """A book at ``approved`` with two page plates + cover + a portrait, style engraving."""
    book = cfg.work_dir / book_id
    prompts = book / "prompts"
    prompts.mkdir(parents=True, exist_ok=True)
    for pid, text, avoid in [
        ("0001", "a lamplit workshop", ["modern dress", "machinery"]),
        ("0003", "a clock tower at dusk", None),
        ("cover", "19th-century engraving frontispiece for the book", None),
        ("portrait-the-clockmaker", "19th-century engraved portrait of a bust", None),
    ]:
        (prompts / f"{pid}.json").write_text(
            json.dumps(_prompt_doc(pid, text, avoid)), encoding="utf-8")
    (book / "selection.json").write_text(json.dumps({
        "preset": "classic",
        "params": {"min_gap": 2, "max_gap": 6, "salience_floor": 0.55,
                   "chapter_open": True, "scene_boundary": True},
        "plates": [
            {"page_id": "0001", "reason": "chapter_open", "salience": 0.8,
             "status": "approved", "added_in_revision": 1},
            {"page_id": "0003", "reason": "fill", "salience": 0.6,
             "status": "approved", "added_in_revision": 1},
        ],
    }), encoding="utf-8")
    Job(id=book_id, book_id=book_id, state=JobState.APPROVED, started=True,
        bake_config={"style_id": "engraving"}).save(cfg)


def _runner(cfg: Config, client) -> Runner:
    # Portraits render in their own phase then the runner auto-advances through portraits_review
    # (no per-book portrait_review flag on these fixtures) into the page render (ADR-0025).
    phases = [PortraitRenderEnter(), PortraitRender(client=client), Render(client=client)]
    return Runner(cfg, phases, sleep=_noop_sleep, wake=lambda _c: None, gpu_gate=_gate_up)


def _drive(cfg: Config, client, *, book_id: str = "b", max_ticks: int = 16,
           until=(JobState.RENDERED, JobState.FAILED, JobState.WAITING_GPU)) -> Job:
    runner = _runner(cfg, client)
    for _ in range(max_ticks):
        asyncio.run(runner.tick())
        job = jobmod.load(cfg, book_id)
        if job.state in until:
            return job
    return jobmod.load(cfg, book_id)


def _png_size(path: Path) -> tuple[int, int]:
    img = Image.open(io.BytesIO(path.read_bytes()))
    img.verify()
    return Image.open(io.BytesIO(path.read_bytes())).size


def _webp_width(path: Path) -> int:
    return Image.open(io.BytesIO(path.read_bytes())).size[0]


@respx.mock
def test_render_produces_pixels_derivatives_and_provenance(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _seed(cfg)
    respx.post(f"{TTS}/v1/models/unload").mock(return_value=httpx.Response(200, json={}))

    job = _drive(cfg, FakeImagegen())
    assert job.state == JobState.RENDERED, f"stuck at {job.state}"
    assert job.render_stub is False

    book = cfg.work_dir / "b"
    # Archival PNGs at the §10 sizes, in the §4.2 bundle layout.
    assert _png_size(book / "images" / "plates" / "0001.png") == (832, 1216)
    assert _png_size(book / "images" / "plates" / "0003.png") == (832, 1216)
    assert _png_size(book / "images" / "cover.png") == (832, 1216)
    assert _png_size(book / "images" / "portraits" / "the-clockmaker.png") == (1024, 1024)

    # WebP derivatives: web (≤max) + 320w thumb for each asset.
    assert _webp_width(book / "images" / "web" / "plates" / "0001.webp") == 832  # ≤1080, no upscale
    assert _webp_width(book / "images" / "thumbs" / "plates" / "0001.webp") == 320
    assert _webp_width(book / "images" / "web" / "portraits" / "the-clockmaker.webp") == 768  # ≤768
    assert (book / "images" / "web" / "cover.webp").is_file()
    assert (book / "images" / "thumbs" / "cover.webp").is_file()

    # Prompt provenance: page plate style-wrapped, negative carries style + avoid, render block set.
    p1 = json.loads((book / "prompts" / "0001.json").read_text("utf-8"))
    assert p1["wrapped_prompt"].startswith("19th-century steel engraving")
    assert "a lamplit workshop" in p1["wrapped_prompt"]
    assert p1["negative_prompt"].startswith("photo, color photograph")
    assert p1["negative_prompt"].endswith("modern dress, machinery")
    assert p1["render"]["attempts"] == 1
    assert p1["render"]["params_echo"]["width"] == 832

    # Cover pseudo-plate is pre-wrapped by P5 → passed through un-rewrapped.
    cover = json.loads((book / "prompts" / "cover.json").read_text("utf-8"))
    assert cover["wrapped_prompt"] == cover["final_subject_prompt"]

    # Page plates flip to rendered; pseudo-plates have no selection entry to touch.
    selection = json.loads((book / "selection.json").read_text("utf-8"))
    assert {p["page_id"]: p["status"] for p in selection["plates"]} == {
        "0001": "rendered", "0003": "rendered"}


@respx.mock
def test_compound_plate_is_style_wrapped_and_marked_rendered(tmp_path) -> None:
    # An evenly-spaced extra ('0001-2') must take the page-plate path (style-wrapped + marked
    # rendered), not be mistaken for a pre-wrapped pseudo-plate. Guards the .isdigit() -> regex fix.
    cfg = _cfg(tmp_path)
    book = cfg.work_dir / "b"
    prompts = book / "prompts"
    prompts.mkdir(parents=True, exist_ok=True)
    for pid, text in [("0001", "the first half"), ("0001-2", "the second half"),
                      ("cover", "frontispiece")]:
        (prompts / f"{pid}.json").write_text(json.dumps(_prompt_doc(pid, text)), encoding="utf-8")
    (book / "selection.json").write_text(json.dumps({
        "preset": "lavish",
        "params": {"min_gap": 1, "max_gap": 3, "salience_floor": 0.4,
                   "chapter_open": True, "scene_boundary": True},
        "plates": [
            {"page_id": "0001", "reason": "chapter_open", "salience": 0.8,
             "status": "approved", "added_in_revision": 1},
            {"page_id": "0001", "plate_id": "0001-2", "anchor": 20, "segment_index": 1,
             "reason": "segment", "salience": 0.8, "status": "approved", "added_in_revision": 1},
        ],
    }), encoding="utf-8")
    Job(id="b", book_id="b", state=JobState.APPROVED, started=True,
        bake_config={"style_id": "engraving"}).save(cfg)
    respx.post(f"{TTS}/v1/models/unload").mock(return_value=httpx.Response(200, json={}))

    job = _drive(cfg, FakeImagegen())
    assert job.state == JobState.RENDERED, f"stuck at {job.state}"

    # Rendered to its own file at the §10 plate size.
    assert _png_size(book / "images" / "plates" / "0001-2.png") == (832, 1216)
    # Style-wrapped (page-plate path), not passed through like a pseudo-plate.
    extra = json.loads((prompts / "0001-2.json").read_text("utf-8"))
    assert extra["wrapped_prompt"].startswith("19th-century steel engraving")
    assert "the second half" in extra["wrapped_prompt"]
    # Its own selection entry flipped to rendered, independently of the base plate.
    selection = json.loads((book / "selection.json").read_text("utf-8"))
    statuses = {p.get("plate_id", p["page_id"]): p["status"] for p in selection["plates"]}
    assert statuses == {"0001": "rendered", "0001-2": "rendered"}


@respx.mock
def test_unload_happens_before_any_render(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _seed(cfg)
    events: list[str] = []

    def _unload(_request: httpx.Request) -> httpx.Response:
        events.append("unload")
        return httpx.Response(200, json={})

    respx.post(f"{TTS}/v1/models/unload").mock(side_effect=_unload)

    class _RecordingImagegen(FakeImagegen):
        async def txt2img(self, *args, **kwargs) -> bytes:
            events.append("txt2img")
            return await super().txt2img(*args, **kwargs)

    job = _drive(cfg, _RecordingImagegen())
    assert job.state == JobState.RENDERED
    assert "unload" in events and "txt2img" in events
    assert events.index("unload") < events.index("txt2img")  # §7.4: TTS freed before SDXL


@respx.mock
def test_unload_failure_parks_waiting_gpu(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _seed(cfg)
    respx.post(f"{TTS}/v1/models/unload").mock(return_value=httpx.Response(503, json={
        "error": {"code": "busy"}}))

    job = _drive(cfg, FakeImagegen(), max_ticks=6)
    assert job.state == JobState.WAITING_GPU  # unload failed → never rendered
    assert not (cfg.work_dir / "b" / "images" / "plates" / "0001.png").is_file()


def _seed_for_reference(cfg, depicted: list[str]) -> tuple[Path, Path]:
    """A one-page book with one major (portrait-bearing) character. Returns ``(book, prompts)``.

    ``depicted`` drives the page plate's ``derived.depicted`` — its *length* is what selects the
    conditioning strength (ADR-0028), so a one- vs two-name list is the whole difference between
    the two tests that use this.
    """
    book = cfg.work_dir / "b"
    prompts = book / "prompts"
    prompts.mkdir(parents=True, exist_ok=True)
    page = _prompt_doc("0001", "the clockmaker at his bench")
    page["derived"]["depicted"] = depicted  # "the Clockmaker" matches the cast name below
    (prompts / "0001.json").write_text(json.dumps(page), encoding="utf-8")
    (prompts / "portrait-clockmaker.json").write_text(
        json.dumps(_prompt_doc("portrait-clockmaker", "engraved bust of the clockmaker")),
        encoding="utf-8")
    (book / "cast.json").write_text(json.dumps({
        "characters": [{"slug": "clockmaker", "name": "the Clockmaker", "aliases": [],
                        "mention_pages": ["0001"], "descriptors": [], "is_person": True,
                        "major": True, "visual_description": "an old man",
                        "one_line": "an old man"}],
    }), encoding="utf-8")
    (book / "selection.json").write_text(json.dumps({
        "preset": "classic",
        "params": {"min_gap": 2, "max_gap": 6, "salience_floor": 0.55,
                   "chapter_open": True, "scene_boundary": True},
        "plates": [{"page_id": "0001", "reason": "chapter_open", "salience": 0.8,
                    "status": "approved", "added_in_revision": 1}],
    }), encoding="utf-8")
    return book, prompts


@respx.mock
def test_page_plate_uses_depicted_characters_portrait_as_reference(tmp_path) -> None:
    # Character consistency (ADR-0023): a page plate whose derived.depicted names a major with a
    # portrait renders with that portrait's bytes as a reference; the portrait renders first so the
    # file exists; cover/portrait plates pass no reference.
    cfg = _cfg(tmp_path)
    book, prompts = _seed_for_reference(cfg, depicted=["the Clockmaker"])
    Job(id="b", book_id="b", state=JobState.APPROVED, started=True,
        bake_config={"style_id": "engraving"}).save(cfg)
    respx.post(f"{TTS}/v1/models/unload").mock(return_value=httpx.Response(200, json={}))

    captured: list[tuple[str, object]] = []

    class _RefRecording(FakeImagegen):
        async def txt2img(self, *args, **kwargs) -> bytes:
            captured.append((args[0], kwargs.get("references")))  # (wrapped_prompt, references)
            return await super().txt2img(*args, **kwargs)

    job = _drive(cfg, _RefRecording())
    assert job.state == JobState.RENDERED, f"stuck at {job.state}"

    # Exactly one call — the page plate — carried a reference; the portrait plate carried none.
    with_refs = [(p, r) for (p, r) in captured if r]
    assert len(with_refs) == 1
    page_prompt, refs = with_refs[0]
    assert "the clockmaker at his bench" in page_prompt  # the page plate, not the portrait
    assert isinstance(refs, list) and len(refs) == 1
    # The reference bytes are exactly the rendered portrait PNG (rendered first, hence available).
    assert refs[0] == (book / "images" / "portraits" / "clockmaker.png").read_bytes()

    # ADR-0026: which face conditioned the plate is recorded, so a mis-anchored plate is findable
    # without eyeballing the art. Pseudo-plates record no reference.
    page_doc = json.loads((prompts / "0001.json").read_text(encoding="utf-8"))
    assert page_doc["render"]["reference_slug"] == "clockmaker"
    portrait_doc = json.loads((prompts / "portrait-clockmaker.json").read_text(encoding="utf-8"))
    assert portrait_doc["render"]["reference_slug"] is None


@respx.mock
def test_multi_figure_plate_sends_a_weaker_later_anchor_to_imagegen(tmp_path) -> None:
    """ADR-0028: the tuned conditioning actually reaches the client, not just the pure helper."""
    cfg = _cfg(tmp_path)
    book, prompts = _seed_for_reference(cfg, depicted=["the clockmaker", "the stranger"])
    Job(id="b", book_id="b", state=JobState.APPROVED, started=True,
        bake_config={"style_id": "engraving"}).save(cfg)
    respx.post(f"{TTS}/v1/models/unload").mock(return_value=httpx.Response(200, json={}))

    calls: list[dict] = []

    class _KwargRecording(FakeImagegen):
        async def txt2img(self, *args, **kwargs) -> bytes:
            calls.append(kwargs)
            return await super().txt2img(*args, **kwargs)

    job = _drive(cfg, _KwargRecording())
    assert job.state == JobState.RENDERED, f"stuck at {job.state}"

    conditioned = [c for c in calls if c.get("references")]
    assert len(conditioned) == 1
    assert conditioned[0]["reference_strength"] == 0.35
    assert conditioned[0]["reference_start"] == 0.4

    # The portrait plate itself is unconditioned and must not carry tuning at all.
    unconditioned = [c for c in calls if not c.get("references")]
    assert unconditioned
    assert all(c.get("reference_strength") is None for c in unconditioned)


@respx.mock
def test_render_is_idempotent(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _seed(cfg)
    respx.post(f"{TTS}/v1/models/unload").mock(return_value=httpx.Response(200, json={}))

    _drive(cfg, FakeImagegen())
    png = cfg.work_dir / "b" / "images" / "plates" / "0001.png"
    webp = cfg.work_dir / "b" / "images" / "web" / "plates" / "0001.webp"
    first_png, first_webp = png.read_bytes(), webp.read_bytes()

    # Re-run from approved: unit_done sees the artifacts and skips; bytes unchanged.
    job = jobmod.load(cfg, "b")
    job.state = JobState.APPROVED
    job.save(cfg)
    _drive(cfg, FakeImagegen())
    assert png.read_bytes() == first_png
    assert webp.read_bytes() == first_webp


# --- optional portrait-review gate (ADR-0025) -------------------------------


@respx.mock
def test_portrait_review_off_auto_advances_through_the_gate(tmp_path) -> None:
    # Default (no per-book flag): the runner auto-advances portraits_review -> rendering, so the
    # split is invisible — the book renders straight to `rendered`, byte-for-byte as before.
    cfg = _cfg(tmp_path)
    _seed(cfg)
    respx.post(f"{TTS}/v1/models/unload").mock(return_value=httpx.Response(200, json={}))

    job = _drive(cfg, FakeImagegen())
    assert job.state == JobState.RENDERED
    book = cfg.work_dir / "b"
    assert (book / "images" / "portraits" / "the-clockmaker.png").is_file()
    assert (book / "images" / "plates" / "0001.png").is_file()


@respx.mock
def test_portrait_review_on_parks_blank_no_portraits_or_pages(tmp_path) -> None:
    # Curated gate (ADR-0029): with the per-book flag set the bake stops at portraits_review with
    # NOTHING drawn — no portrait, no page plate. The owner generates/uploads each portrait there.
    cfg = _cfg(tmp_path)
    _seed(cfg)
    job = jobmod.load(cfg, "b")
    job.bake_config["portrait_review"] = True
    job.save(cfg)
    respx.post(f"{TTS}/v1/models/unload").mock(return_value=httpx.Response(200, json={}))

    job = _drive(cfg, FakeImagegen(),
                 until=(JobState.PORTRAITS_REVIEW, JobState.RENDERED, JobState.FAILED))
    assert job.state == JobState.PORTRAITS_REVIEW, f"expected gate, got {job.state}"
    book = cfg.work_dir / "b"
    assert not (book / "images" / "portraits" / "the-clockmaker.png").is_file()  # blank gate
    assert not (book / "images" / "plates" / "0001.png").is_file()  # page plate NOT yet drawn


@respx.mock
def test_curated_blanks_fill_from_default_at_render(tmp_path) -> None:
    # Approving with a blank portrait draws it from its default prompt during the page render (so
    # the outcome matches the no-gate default), then the page plates draw.
    cfg = _cfg(tmp_path)
    _seed(cfg)
    job = jobmod.load(cfg, "b")
    job.bake_config["portrait_review"] = True
    job.save(cfg)
    respx.post(f"{TTS}/v1/models/unload").mock(return_value=httpx.Response(200, json={}))

    job = _drive(cfg, FakeImagegen(),
                 until=(JobState.PORTRAITS_REVIEW, JobState.RENDERED, JobState.FAILED))
    assert job.state == JobState.PORTRAITS_REVIEW

    from scriptorium.bake.approve import approve_portraits
    approve_portraits(cfg, jobmod.load(cfg, "b"))  # portraits_review -> rendering

    job = _drive(cfg, FakeImagegen())
    assert job.state == JobState.RENDERED
    book = cfg.work_dir / "b"
    # The blank portrait was filled (at the §10 portrait size), then the page plate drew.
    assert _png_size(book / "images" / "portraits" / "the-clockmaker.png") == (1024, 1024)
    assert (book / "images" / "plates" / "0001.png").is_file()
    portrait = json.loads((book / "prompts" / "portrait-the-clockmaker.json").read_text("utf-8"))
    assert portrait["render"]["attempts"] == 1  # drawn exactly once


@respx.mock
def test_curated_render_does_not_override_owner_portrait(tmp_path) -> None:
    # A portrait the owner already made at the gate is left untouched by the page-render blank-fill
    # (existence-based skip), so their choice survives.
    cfg = _cfg(tmp_path)
    _seed(cfg)
    job = jobmod.load(cfg, "b")
    job.bake_config["portrait_review"] = True
    job.save(cfg)
    respx.post(f"{TTS}/v1/models/unload").mock(return_value=httpx.Response(200, json={}))

    _drive(cfg, FakeImagegen(),
           until=(JobState.PORTRAITS_REVIEW, JobState.RENDERED, JobState.FAILED))
    book = cfg.work_dir / "b"
    portrait_png = book / "images" / "portraits" / "the-clockmaker.png"

    # Owner clicks "Generate" for this one portrait (what regen_plate does at the gate).
    asyncio.run(render_plate(cfg, jobmod.load(cfg, "b"), "portrait-the-clockmaker", FakeImagegen()))
    before = portrait_png.read_bytes()

    from scriptorium.bake.approve import approve_portraits
    approve_portraits(cfg, jobmod.load(cfg, "b"))
    job = _drive(cfg, FakeImagegen())
    assert job.state == JobState.RENDERED
    assert portrait_png.read_bytes() == before  # not re-rendered
    portrait = json.loads((book / "prompts" / "portrait-the-clockmaker.json").read_text("utf-8"))
    assert portrait["render"]["attempts"] == 1


@respx.mock
def test_bake_model_reaches_the_imagegen_client(tmp_path) -> None:
    # ADR-0030: a book's chosen base model (bake_config["model"]) is forwarded as the txt2img
    # `checkpoint` for every plate; unset → checkpoint stays None (service default).
    cfg = _cfg(tmp_path)
    _seed(cfg)
    job = jobmod.load(cfg, "b")
    job.bake_config["model"] = "dreamshaper.safetensors"
    job.save(cfg)
    respx.post(f"{TTS}/v1/models/unload").mock(return_value=httpx.Response(200, json={}))

    seen: list[str | None] = []

    class _RecordingImagegen(FakeImagegen):
        async def txt2img(self, *args, checkpoint=None, **kwargs) -> bytes:
            seen.append(checkpoint)
            return await super().txt2img(*args, checkpoint=checkpoint, **kwargs)

    job = _drive(cfg, _RecordingImagegen())
    assert job.state == JobState.RENDERED
    assert seen, "no plate rendered"
    assert set(seen) == {"dreamshaper.safetensors"}  # every plate used the chosen model


@respx.mock
def test_off_flag_portrait_rendered_once_not_double(tmp_path) -> None:
    # Byte-stability guard: with the flag off, PortraitRender draws the portrait and Render's
    # portraits-first list skips it (existence-based), so it is rendered exactly once as before.
    cfg = _cfg(tmp_path)
    _seed(cfg)
    respx.post(f"{TTS}/v1/models/unload").mock(return_value=httpx.Response(200, json={}))

    job = _drive(cfg, FakeImagegen())
    assert job.state == JobState.RENDERED
    portrait = json.loads(
        (cfg.work_dir / "b" / "prompts" / "portrait-the-clockmaker.json").read_text("utf-8"))
    assert portrait["render"]["attempts"] == 1
