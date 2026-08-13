"""Post-publish per-plate picture edits (private per user) — fixture-based, no GPU/network.

Covers the img2img client wiring (``initImage``/``denoise`` only when set) and the edits service +
endpoints: context pre-fill, candidate generation, commit into the private overlay, immutability of
``library/`` (the frozen bundle is byte-unchanged), and ``GpuUnavailable`` → 503. Image content is
never asserted — only shape, paths, and that files land under ``artsets/`` (CLAUDE.md).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from scriptorium import schemas
from scriptorium.app import app
from scriptorium.artsets import edits as edits_service
from scriptorium.bake.phases.base import GpuUnavailable
from scriptorium.config import Config, load_config
from scriptorium.render.imagegen import FakeImagegen

_USER = "kris"
_BOOK = "usr-aaaaaaaaaaaa"


def _cfg(tmp_path: Path, *, imagegen_url: str | None = None) -> Config:
    repo_shared = Path(__file__).resolve().parents[2] / "shared"
    return Config(
        data_dir=tmp_path, port=8720, tts_url=None, imagegen_url=imagegen_url, gpu_mac=None,
        gpu_wol_enabled=False, runner_tick_s=1, shared_dir=repo_shared,
    )


def _publish_book(cfg: Config, *, book: str = _BOOK, plate: str = "0001") -> None:
    """A minimal published bundle: meta + one plate prompt + its archival PNG + a captioned page."""
    lib = cfg.library_dir / book
    (lib / "prompts").mkdir(parents=True, exist_ok=True)
    (lib / "images" / "plates").mkdir(parents=True, exist_ok=True)
    (lib / "pages").mkdir(parents=True, exist_ok=True)
    (lib / "meta.json").write_text(json.dumps({
        "book_id": book, "revision": 1,
        "bake": {"models": {"imagegen": "sd_xl_base_1.0.safetensors"}},
    }), encoding="utf-8")
    (lib / "prompts" / f"{plate}.json").write_text(json.dumps({
        "final_subject_prompt": "a lamplit workshop",
        "negative_prompt": "blurry",
        "render": {"params_echo": {"seed": 7, "width": 832, "height": 1216}},
    }), encoding="utf-8")
    (lib / "pages" / f"{plate}.json").write_text(json.dumps({
        "id": f"pg-{plate}", "seq": 1, "text": "Body.",
        "ledger": {"best_visual_beat": "a lamp glows"},
    }), encoding="utf-8")
    # A real (deterministic) PNG so make_derivatives + img2img have valid image bytes.
    png = FakeImagegen().render("original", width=832, height=1216)
    (lib / "images" / "plates" / f"{plate}.png").write_bytes(png)


# --- img2img client wiring --------------------------------------------------


@respx.mock
def test_client_sends_init_image_and_denoise_only_when_set(tmp_path) -> None:
    route = respx.post("http://ig.local/generate").mock(
        return_value=httpx.Response(200, content=b"PNGBYTES")
    )
    from scriptorium.render.imagegen import RealImagegenClient

    client = RealImagegenClient(_cfg(tmp_path, imagegen_url="http://ig.local"))
    asyncio.run(client.txt2img("p", init_image=b"\x89PNGstart", denoise=0.5))
    body = json.loads(route.calls[-1].request.content)
    assert body["initImage"]  # base64 of the starting image
    assert body["denoise"] == 0.5

    asyncio.run(client.txt2img("p"))  # a plain txt2img must not carry img2img fields
    body2 = json.loads(route.calls[-1].request.content)
    assert "initImage" not in body2
    assert "denoise" not in body2


def test_fake_digest_changes_with_init_image(tmp_path) -> None:
    fake = FakeImagegen()
    plain = fake.render("p", width=64, height=64)
    with_init = fake.render("p", width=64, height=64, init_image=b"start", denoise=0.6)
    assert plain != with_init  # img2img must produce a visibly distinct stand-in


@respx.mock
def test_client_sends_quality_only_when_set(tmp_path) -> None:
    route = respx.post("http://ig.local/generate").mock(
        return_value=httpx.Response(200, content=b"PNGBYTES")
    )
    from scriptorium.render.imagegen import RealImagegenClient

    client = RealImagegenClient(_cfg(tmp_path, imagegen_url="http://ig.local"))
    asyncio.run(client.txt2img("p", quality="high"))
    assert json.loads(route.calls[-1].request.content)["quality"] == "high"

    asyncio.run(client.txt2img("p"))  # default tier must not carry the field (byte-stable)
    assert "quality" not in json.loads(route.calls[-1].request.content)


def test_fake_bytes_stable_without_quality_but_change_with_it(tmp_path) -> None:
    fake = FakeImagegen()
    base = fake.render("p", width=64, height=64)
    # Unset quality is byte-identical to the pre-edit fake (determinism/round-trip fixtures).
    assert fake.render("p", width=64, height=64, quality=None) == base
    # A set tier must produce a visibly distinct stand-in.
    assert fake.render("p", width=64, height=64, quality="high") != base


# --- service: context / candidate / commit ----------------------------------


def test_plate_context_prefills_prompt_and_caption(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _publish_book(cfg)
    ctx = asyncio.run(edits_service.plate_context(cfg, _USER, _BOOK, "0001"))
    assert ctx["prompt"] == "a lamplit workshop"
    assert ctx["caption"] == "a lamp glows"
    assert ctx["denoise_default"] == edits_service.DENOISE_DEFAULT
    assert (ctx["width"], ctx["height"]) == (832, 1216)
    # The pickers get the local style catalog even with no imagegen service reachable.
    assert any(s["id"] == "comic-book" for s in ctx["styles"])
    assert "quality_default" in ctx and "style_id" in ctx


def _commit_one(cfg: Config, *, caption: str = "a brighter lamp") -> dict:
    token = asyncio.run(edits_service.generate_candidate(
        cfg, _USER, _BOOK, "0001", prompt="a lamplit workshop, warmer",
        denoise=0.55, client=FakeImagegen(),
    ))["token"]
    return edits_service.commit_edit(cfg, _USER, _BOOK, "0001", token=token, caption=caption)


def test_commit_writes_overlay_and_leaves_library_untouched(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _publish_book(cfg)
    lib = cfg.library_dir / _BOOK
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(lib.rglob("*")) if p.is_file()}

    _commit_one(cfg)

    # Nothing in the published bundle changed (frozen pages, immutability §4.4).
    after = {p: hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(lib.rglob("*")) if p.is_file()}
    assert after == before

    # The override landed in the private edits overlay, outside library/, under its scope (ADR-0035
    # — the base book is "default").
    overlay = cfg.artsets_dir / _USER / _BOOK / "edits"
    assert (overlay / "images" / "web" / "plates" / "default" / "0001.webp").is_file()
    assert (overlay / "images" / "thumbs" / "plates" / "default" / "0001.webp").is_file()
    assert (overlay / "images" / "plates" / "default" / "0001.png").is_file()  # archival source
    edits_doc = json.loads((overlay / "edits.json").read_text("utf-8"))
    schemas.validate("artset-edits", edits_doc)
    assert edits_doc["plates"]["0001"]["default"]["caption"] == "a brighter lamp"
    assert edits_doc["plates"]["0001"]["default"]["denoise"] == 0.55


def test_overlay_manifest_marks_edits_json_reader_required(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _publish_book(cfg)
    _commit_one(cfg)
    manifest = json.loads(
        (cfg.artsets_dir / _USER / _BOOK / "edits" / "manifest.json").read_text("utf-8")
    )
    assert "edits.json" in manifest["reader_required"]
    paths = {f["path"] for f in manifest["files"]}
    assert "images/web/plates/default/0001.webp" in paths


def test_reedit_starts_from_prior_overlay_image(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _publish_book(cfg)
    _commit_one(cfg, caption="first")
    overlay_png = (
        cfg.artsets_dir / _USER / _BOOK / "edits" / "images" / "plates" / "default" / "0001.png"
    )
    first = overlay_png.read_bytes()
    # The context caption now reflects the committed override, not the page ledger.
    ctx = asyncio.run(edits_service.plate_context(cfg, _USER, _BOOK, "0001"))
    assert ctx["caption"] == "first"
    _commit_one(cfg, caption="second")
    assert overlay_png.read_bytes() != first  # overwritten in place (private, no -rN history)


# --- fidelity: an edit reproduces the ACTIVE reader's style/model (ADR-0034) -----------------


class _SpyImagegen:
    """Records the txt2img request so the test can assert the render was style/model-matched."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def txt2img(
        self, prompt, negative="", width=832, height=1216, seed=None, *,
        style=None, checkpoint=None, references=None, reference_strength=None,
        reference_start=None, init_image=None, denoise=None, quality=None,
    ) -> bytes:
        self.calls.append({
            "prompt": prompt, "style": style, "checkpoint": checkpoint,
            "references": references, "quality": quality,
        })
        return FakeImagegen().render(prompt, width=width, height=height)

    async def models(self) -> dict:
        return {"models": ["juggernautXL_ragnarok.safetensors"], "default": None}

    async def health(self) -> bool:
        return True


_SET_ID = "set-0123456789ab"
_SET_MODEL = "juggernautXL_ragnarok.safetensors"


def _add_comic_set(cfg: Config, *, book: str = _BOOK, plate: str = "0001") -> None:
    """A ready 'Comic Book' style set over the published book: its own checkpoint + rendered plate +
    portrait, plus the base book's cast + a depicted label that resolves to it."""
    lib = cfg.library_dir / book
    # Base book gains a cast + a depicted label so the plate has a character to pin likeness on.
    (lib / "cast.json").write_text(json.dumps({
        "characters": [{"slug": "hero", "name": "Hero", "aliases": []}],
    }), encoding="utf-8")
    doc = json.loads((lib / "prompts" / f"{plate}.json").read_text("utf-8"))
    doc["derived"] = {"depicted": ["Hero"]}
    (lib / "prompts" / f"{plate}.json").write_text(json.dumps(doc), encoding="utf-8")

    set_dir = cfg.artsets_dir / _USER / book / _SET_ID
    (set_dir / "images" / "plates").mkdir(parents=True, exist_ok=True)
    (set_dir / "images" / "portraits").mkdir(parents=True, exist_ok=True)
    (set_dir / "set.json").write_text(json.dumps({
        "book_id": book, "user_id": _USER, "set_id": _SET_ID, "kind": "style",
        "style_id": "comic-book", "custom_style": None, "model": _SET_MODEL,
        "source_revision": 1, "status": "ready",
    }), encoding="utf-8")
    (set_dir / "manifest.json").write_text(json.dumps({"files": []}), encoding="utf-8")
    (set_dir / "images" / "plates" / f"{plate}.png").write_bytes(
        FakeImagegen().render("comic-plate", width=832, height=1216)
    )
    (set_dir / "images" / "portraits" / "hero.png").write_bytes(
        FakeImagegen().render("hero-portrait", width=1024, height=1024)
    )


def test_edit_on_active_set_reproduces_its_style_and_model(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _publish_book(cfg)
    _add_comic_set(cfg)
    spy = _SpyImagegen()
    asyncio.run(edits_service.generate_candidate(
        cfg, _USER, _BOOK, "0001", prompt="a lamplit workshop",
        set_id=_SET_ID, quality="high", client=spy,
    ))
    call = spy.calls[-1]
    # The render is matched to the comic set: its checkpoint, its LoRA style preset, its quality —
    # and the style wrapping is applied (wrapped prompt differs from the bare subject).
    assert call["checkpoint"] == _SET_MODEL
    assert call["style"] == "comic book"
    assert call["quality"] == "high"
    assert call["prompt"] != "a lamplit workshop"
    # The plate's cast portrait is used to keep the character on-model.
    assert call["references"] is not None


def test_edit_records_style_and_model_in_edits_json(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _publish_book(cfg)
    _add_comic_set(cfg)
    token = asyncio.run(edits_service.generate_candidate(
        cfg, _USER, _BOOK, "0001", prompt="a lamplit workshop",
        set_id=_SET_ID, client=FakeImagegen(),
    ))["token"]
    edits_service.commit_edit(cfg, _USER, _BOOK, "0001", token=token, caption="c")
    doc = json.loads(
        (cfg.artsets_dir / _USER / _BOOK / "edits" / "edits.json").read_text("utf-8")
    )
    schemas.validate("artset-edits", doc)
    # The edit is filed under the set's scope (not "default"), and is self-describing.
    entry = doc["plates"]["0001"][_SET_ID]
    assert entry["style_id"] == "comic-book"
    assert entry["model"] == _SET_MODEL
    assert entry["set_id"] == _SET_ID


def test_edit_on_set_starts_from_set_plate_not_base(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _publish_book(cfg)
    _add_comic_set(cfg)
    base = (cfg.library_dir / _BOOK / "images" / "plates" / "0001.png").read_bytes()
    set_plate = (
        cfg.artsets_dir / _USER / _BOOK / _SET_ID / "images" / "plates" / "0001.png"
    ).read_bytes()
    assert base != set_plate  # precondition: the set re-illustrated the plate
    got = edits_service._current_plate_png(cfg, _USER, _BOOK, "0001", _SET_ID)
    assert got == set_plate  # img2img starts from what the reader is actually viewing


# --- scoping: an edit only overrides the reader it was made on (ADR-0035) ---------------------


def test_edit_on_set_is_scoped_to_that_set_only(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _publish_book(cfg)
    _add_comic_set(cfg)
    token = asyncio.run(edits_service.generate_candidate(
        cfg, _USER, _BOOK, "0001", prompt="p", set_id=_SET_ID, client=FakeImagegen(),
    ))["token"]
    edits_service.commit_edit(cfg, _USER, _BOOK, "0001", token=token, caption="comic caption")

    overlay = cfg.artsets_dir / _USER / _BOOK / "edits"
    # The replacement lives under the SET's scope, and NOT under the base book's "default".
    assert (overlay / "images" / "web" / "plates" / _SET_ID / "0001.webp").is_file()
    assert not (overlay / "images" / "web" / "plates" / "default" / "0001.webp").exists()

    # The base book (default reader) does not see the comic edit: its context falls back to the page
    # caption, and its img2img starts from the base plate — switching off the set restores it.
    base_ctx = asyncio.run(edits_service.plate_context(cfg, _USER, _BOOK, "0001"))
    assert base_ctx["caption"] == "a lamp glows"
    base_start = edits_service._current_plate_png(cfg, _USER, _BOOK, "0001", None)
    assert base_start == (cfg.library_dir / _BOOK / "images" / "plates" / "0001.png").read_bytes()

    # The comic reader DOES resume from its own edit.
    set_ctx = asyncio.run(edits_service.plate_context(
        cfg, _USER, _BOOK, "0001", set_id=_SET_ID, client=FakeImagegen(),
    ))
    assert set_ctx["caption"] == "comic caption"


def test_edits_on_base_and_set_coexist(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _publish_book(cfg)
    _add_comic_set(cfg)
    t1 = asyncio.run(edits_service.generate_candidate(
        cfg, _USER, _BOOK, "0001", prompt="p", client=FakeImagegen(),
    ))["token"]
    edits_service.commit_edit(cfg, _USER, _BOOK, "0001", token=t1, caption="base")
    t2 = asyncio.run(edits_service.generate_candidate(
        cfg, _USER, _BOOK, "0001", prompt="p", set_id=_SET_ID, client=FakeImagegen(),
    ))["token"]
    edits_service.commit_edit(cfg, _USER, _BOOK, "0001", token=t2, caption="comic")

    overlay = cfg.artsets_dir / _USER / _BOOK / "edits"
    assert (overlay / "images" / "web" / "plates" / "default" / "0001.webp").is_file()
    assert (overlay / "images" / "web" / "plates" / _SET_ID / "0001.webp").is_file()
    doc = json.loads((overlay / "edits.json").read_text("utf-8"))
    schemas.validate("artset-edits", doc)
    assert doc["plates"]["0001"]["default"]["caption"] == "base"
    assert doc["plates"]["0001"][_SET_ID]["caption"] == "comic"


def test_commit_migrates_legacy_flat_edit(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _publish_book(cfg)
    # A pre-ADR-0035 flat edits.json (the entry sat directly under plate_id, with no scope key).
    overlay = cfg.artsets_dir / _USER / _BOOK / "edits"
    overlay.mkdir(parents=True, exist_ok=True)
    legacy_entry = {"caption": "old", "prompt": "p", "created": "2020-01-01T00:00:00+00:00"}
    (overlay / "edits.json").write_text(json.dumps({
        "book_id": _BOOK, "user_id": _USER, "source_revision": 1,
        "plates": {"0002": legacy_entry},
    }), encoding="utf-8")
    # A new scoped commit succeeds; the un-scopeable legacy entry is dropped (else it fails schema).
    _commit_one(cfg)
    doc = json.loads((overlay / "edits.json").read_text("utf-8"))
    schemas.validate("artset-edits", doc)
    assert "0002" not in doc["plates"]
    assert doc["plates"]["0001"]["default"]["caption"] == "a brighter lamp"


# --- endpoints --------------------------------------------------------------


@pytest.fixture
def client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setenv("SCRIPTORIUM_DATA", str(tmp_path))
    monkeypatch.setattr("scriptorium.artsets.api._imagegen_client", lambda _cfg: FakeImagegen())
    return TestClient(app)


def test_endpoints_candidate_then_commit(client) -> None:
    _publish_book(load_config())
    ctx = client.get(f"/api/artsets/{_USER}/{_BOOK}/edits/0001/context")
    assert ctx.status_code == 200, ctx.text
    assert ctx.json()["prompt"] == "a lamplit workshop"

    cand = client.post(
        f"/api/artsets/{_USER}/{_BOOK}/edits/0001/candidate",
        json={"prompt": "a lamplit workshop, warmer", "denoise": 0.6},
    )
    assert cand.status_code == 200, cand.text
    token = cand.json()["token"]

    preview = client.get(f"/api/artsets/{_USER}/{_BOOK}/edits/0001/candidate/{token}.png")
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/png"

    done = client.post(
        f"/api/artsets/{_USER}/{_BOOK}/edits/0001/commit",
        json={"token": token, "caption": "warmer lamp"},
    )
    assert done.status_code == 200, done.text
    # The committed overlay is now served as the reserved "edits" set.
    man = client.get(f"/api/artsets/{_USER}/{_BOOK}/edits/manifest")
    assert man.status_code == 200
    assert "edits.json" in man.json()["reader_required"]


def test_candidate_gpu_unavailable_maps_to_503(client, monkeypatch) -> None:
    _publish_book(load_config())

    class _Down:
        async def txt2img(self, *a, **k):
            raise GpuUnavailable("gpu busy")

    monkeypatch.setattr("scriptorium.artsets.api._imagegen_client", lambda _cfg: _Down())
    r = client.post(
        f"/api/artsets/{_USER}/{_BOOK}/edits/0001/candidate", json={"prompt": "x"}
    )
    assert r.status_code == 503


def test_context_unknown_plate_is_404(client) -> None:
    _publish_book(load_config())
    r = client.get(f"/api/artsets/{_USER}/{_BOOK}/edits/9999/context")
    assert r.status_code == 404


def test_commit_unknown_candidate_is_400(client) -> None:
    _publish_book(load_config())
    r = client.post(
        f"/api/artsets/{_USER}/{_BOOK}/edits/0001/commit",
        json={"token": "0" * 16, "caption": "x"},
    )
    assert r.status_code == 400
