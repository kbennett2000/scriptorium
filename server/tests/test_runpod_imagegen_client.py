"""The Runpod render backend (ADR-0038).

`RunpodImagegenClient` implements the same `ImagegenClient` surface as the local
client, so P7 and `render_to_spec` are unchanged and only the injected object differs.
What is asserted here is the wire contract and the failure taxonomy — never image
content (CLAUDE.md).

The failure taxonomy matters more than usual. The runner's whole error model is
built on which exception comes out: `GpuUnavailable` parks the job on `waiting_gpu`
and retries it every tick, `UnitFailed` runs the 10/60/300 s ladder and then records
the plate in `failed_units`, and anything else fails the entire job. A serverless
endpoint fails in ways the local service never did — a queue that sheds 429s, a job
that reaches COMPLETED and reports its own error in the body — so each is pinned.

No network: respx intercepts, and the credential reader is patched so the tests run
on a machine with no Runpod config file.
"""

from __future__ import annotations

import asyncio
import base64
import json
from types import SimpleNamespace

import httpx
import pytest
import respx

from scriptorium.bake.phases.base import GpuUnavailable, PipelineBug, UnitFailed
from scriptorium.render import imagegen as ig
from scriptorium.render.imagegen import (
    RealImagegenClient,
    RunpodImagegenClient,
    build_imagegen_client,
)

_ENDPOINT = "h4rz8tmjkq35fu"
_BASE = f"https://api.runpod.ai/v2/{_ENDPOINT}"
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
_PNG_B64 = base64.b64encode(_PNG).decode("ascii")


@pytest.fixture(autouse=True)
def _no_credential_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never read the real ~/.runpod/config.toml, and never need one to exist."""
    monkeypatch.setattr(ig, "_runpod_auth", lambda: {"Authorization": "Bearer test"})


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retry backoff and poll interval are real seconds; tests should not spend them."""
    async def _instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr(ig.asyncio, "sleep", _instant)


def _cfg(**over: object) -> SimpleNamespace:
    base = {"runpod_endpoint_id": _ENDPOINT, "render_card": None}
    base.update(over)
    return SimpleNamespace(**base)


def _client(**over: object) -> RunpodImagegenClient:
    return RunpodImagegenClient(_cfg(**over))  # type: ignore[arg-type]


def _completed(output: dict) -> httpx.Response:
    return httpx.Response(200, json={"status": "COMPLETED", "output": output})


def _ok_output(**over: object) -> dict:
    out = {
        "image_png_b64": _PNG_B64,
        "model_load_s": 0.0, "render_s": 4.406, "total_s": 4.412,
        "width": 832, "height": 1216, "seed": 5,
        "steps": 25, "cfg": 7, "sampler": "euler", "scheduler": "normal",
        "lora": "ClassipeintXL2.1.safetensors", "ip_adapter": False,
        "reference_strength": None, "reference_start": None,
        "gpu": "cuda:0 NVIDIA GeForce RTX 4090 : cudaMallocAsync",
    }
    out.update(over)
    return out


def _stub(output: dict | None = None) -> None:
    respx.post(f"{_BASE}/run").mock(return_value=httpx.Response(200, json={"id": "job-1"}))
    respx.get(f"{_BASE}/status/job-1").mock(return_value=_completed(output or _ok_output()))


# --- the wire body ----------------------------------------------------------


@respx.mock
def test_minimal_request_body() -> None:
    _stub()
    png = asyncio.run(_client().txt2img("a hollow at dusk", "blurry", 832, 1216, 5))
    assert png == _PNG
    sent = json.loads(respx.calls[0].request.read())
    assert sent == {
        "input": {"prompt": "a hollow at dusk", "negative": "blurry",
                  "seed": 5, "width": 832, "height": 1216}
    }


@respx.mock
def test_reference_travels_base64_with_its_conditioning() -> None:
    """The ADR-0028 pair is the reason the worker grew these inputs at all."""
    _stub()
    asyncio.run(_client().txt2img(
        "two figures", "", 832, 1216, 5,
        references=[b"portrait-bytes"], reference_strength=0.35, reference_start=0.4,
    ))
    sent = json.loads(respx.calls[0].request.read())["input"]
    assert sent["reference_png_b64"] == base64.b64encode(b"portrait-bytes").decode()
    assert sent["reference_strength"] == 0.35
    assert sent["reference_start"] == 0.4


@respx.mock
def test_single_figure_plate_omits_conditioning_so_the_worker_defaults_apply() -> None:
    _stub()
    asyncio.run(_client().txt2img("one figure", "", 832, 1216, 5, references=[b"p"]))
    sent = json.loads(respx.calls[0].request.read())["input"]
    assert "reference_png_b64" in sent
    assert "reference_strength" not in sent
    assert "reference_start" not in sent


@respx.mock
def test_conditioning_without_a_reference_is_not_sent() -> None:
    """Nothing to condition, so the parameter would be meaningless."""
    _stub()
    asyncio.run(_client().txt2img("no ref", "", 832, 1216, 5, reference_strength=0.35))
    sent = json.loads(respx.calls[0].request.read())["input"]
    assert "reference_strength" not in sent


# --- what the worker cannot do, refused loudly ------------------------------


@respx.mock
def test_a_different_checkpoint_raises_rather_than_rendering_the_wrong_model() -> None:
    _stub()
    with pytest.raises(PipelineBug):
        asyncio.run(_client().txt2img("x", "", 832, 1216, 5, checkpoint="other.safetensors"))


@respx.mock
def test_img2img_raises() -> None:
    _stub()
    with pytest.raises(PipelineBug):
        asyncio.run(_client().txt2img("x", "", 832, 1216, 5, init_image=b"png"))


@respx.mock
def test_a_missing_seed_raises_rather_than_being_invented() -> None:
    """An invented seed silently destroys the reproducibility a plate depends on."""
    _stub()
    with pytest.raises(PipelineBug):
        asyncio.run(_client().txt2img("x", "", 832, 1216, None))


def test_animate_parks_rather_than_pretending() -> None:
    with pytest.raises(GpuUnavailable):
        asyncio.run(_client().animate(b"png", "drift"))


def test_unconfigured_endpoint_parks_the_job() -> None:
    with pytest.raises(GpuUnavailable):
        asyncio.run(RunpodImagegenClient(_cfg(runpod_endpoint_id=None)).txt2img(  # type: ignore[arg-type]
            "x", "", 832, 1216, 5))
    assert asyncio.run(RunpodImagegenClient(_cfg(runpod_endpoint_id=None)).health()) is False  # type: ignore[arg-type]


# --- the failure taxonomy ---------------------------------------------------


@respx.mock
def test_error_inside_a_completed_job_is_a_unit_failure() -> None:
    """HTTP 200 + status COMPLETED is not a successful render."""
    _stub({"error": "seed is required"})
    with pytest.raises(UnitFailed, match="seed is required"):
        asyncio.run(_client().txt2img("x", "", 832, 1216, 5))


@respx.mock
def test_terminal_job_failure_is_a_unit_failure() -> None:
    respx.post(f"{_BASE}/run").mock(return_value=httpx.Response(200, json={"id": "job-1"}))
    respx.get(f"{_BASE}/status/job-1").mock(
        return_value=httpx.Response(200, json={"status": "FAILED", "error": "worker died"})
    )
    with pytest.raises(UnitFailed, match="FAILED"):
        asyncio.run(_client().txt2img("x", "", 832, 1216, 5))


@respx.mock
def test_undecodable_image_is_a_unit_failure_not_a_crash() -> None:
    _stub(_ok_output(image_png_b64="!!!not base64!!!"))
    with pytest.raises(UnitFailed):
        asyncio.run(_client().txt2img("x", "", 832, 1216, 5))


@respx.mock
def test_transient_429_retries_then_succeeds() -> None:
    """A shed request is a queue hiccup, not a plate failure — it must not burn a ladder step."""
    responses = [
        httpx.Response(429),
        httpx.Response(500),
        httpx.Response(200, json={"id": "job-1"}),
    ]
    respx.post(f"{_BASE}/run").mock(side_effect=responses)
    respx.get(f"{_BASE}/status/job-1").mock(return_value=_completed(_ok_output()))
    assert asyncio.run(_client().txt2img("x", "", 832, 1216, 5)) == _PNG
    assert respx.calls.call_count == 4  # 3 submits + 1 status


@respx.mock
def test_exhausted_retries_park_the_job() -> None:
    respx.post(f"{_BASE}/run").mock(return_value=httpx.Response(503))
    with pytest.raises(GpuUnavailable):
        asyncio.run(_client().txt2img("x", "", 832, 1216, 5))


@respx.mock
def test_auth_failure_is_not_retried() -> None:
    """A bad credential will still be bad in ten seconds; retrying only hides it."""
    route = respx.post(f"{_BASE}/run").mock(return_value=httpx.Response(401))
    with pytest.raises(PipelineBug, match="API key"):
        asyncio.run(_client().txt2img("x", "", 832, 1216, 5))
    assert route.call_count == 1


# --- the per-plate echo, which is what makes fan-out timings attributable ----


@respx.mock
def test_last_echo_carries_the_timing_and_the_card_but_not_the_image() -> None:
    _stub()
    client = _client()
    asyncio.run(client.txt2img("x", "", 832, 1216, 5))
    echo = client.last_echo
    assert "image_png_b64" not in echo
    assert echo["render_s"] == 4.406
    assert echo["gpu"] == "cuda:0 NVIDIA GeForce RTX 4090 : cudaMallocAsync"
    assert echo["steps"] == 25 and echo["sampler"] == "euler"


@respx.mock
def test_a_substituted_card_warns_and_still_returns_the_render(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Cycle 3 measured a pinned card being substituted silently. The pixels are still
    real, so this is a warning and never a failure — but it must not be silent."""
    _stub(_ok_output(gpu="cuda:0 NVIDIA RTX PRO 6000 Blackwell Server Edition MIG 1g.24gb"))
    client = _client(render_card="NVIDIA GeForce RTX 4090")
    with caplog.at_level("WARNING"):
        assert asyncio.run(client.txt2img("x", "", 832, 1216, 5)) == _PNG
    assert "Blackwell" in caplog.text and "4090" in caplog.text


@respx.mock
def test_the_expected_card_does_not_warn(caplog: pytest.LogCaptureFixture) -> None:
    _stub()
    with caplog.at_level("WARNING"):
        asyncio.run(_client(render_card="NVIDIA GeForce RTX 4090").txt2img("x", "", 832, 1216, 5))
    assert caplog.text == ""


# --- the factory ------------------------------------------------------------


def test_factory_defaults_to_local() -> None:
    cfg = SimpleNamespace(imagegen_url="http://x:8189")
    assert isinstance(build_imagegen_client(cfg), RealImagegenClient)  # type: ignore[arg-type]


def test_factory_selects_runpod_only_when_asked() -> None:
    local = SimpleNamespace(imagegen_url="http://x:8189", render_backend="local")
    remote = SimpleNamespace(imagegen_url="http://x:8189", render_backend="runpod",
                             runpod_endpoint_id=_ENDPOINT, render_card=None)
    assert isinstance(build_imagegen_client(local), RealImagegenClient)  # type: ignore[arg-type]
    assert isinstance(build_imagegen_client(remote), RunpodImagegenClient)  # type: ignore[arg-type]
