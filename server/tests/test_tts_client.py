"""TtsClient tests: the TTS error taxonomy (§8) mapped onto phase-control exceptions.

Every documented status code is exercised against a respx-mocked service and asserted to
raise the correct exception (or return the output on 200). This is BUILD-PLAN S5's "every
TTS error code exercised via respx with the correct job outcome" at the client boundary;
the phase/runner tests then confirm each exception's job-level effect.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
import respx

from scriptorium.bake.phases.base import GpuUnavailable, PipelineBug, UnitFailed
from scriptorium.bake.tts_client import TtsClient
from scriptorium.config import Config

TTS = "http://tts.test:8712"


def _cfg(tmp_path) -> Config:
    return Config(
        data_dir=tmp_path,
        port=8720,
        tts_url=TTS,
        imagegen_url=None,
        gpu_mac=None,
        gpu_wol_enabled=False,
        runner_tick_s=1,
        shared_dir=tmp_path,
    )


def _err(code: str) -> dict:
    return {"error": {"code": code, "message": code, "detail": {}}}


def _transform(tmp_path):
    return TtsClient(_cfg(tmp_path)).transform("cast-mentions", "some page text")


@respx.mock
def test_success_returns_output(tmp_path) -> None:
    output = {"mentions": [{"name": "Weena", "aliases": [], "descriptors": [],
                            "is_person": True}]}
    respx.post(f"{TTS}/v1/transform/cast-mentions").mock(
        return_value=httpx.Response(200, json={"output": output, "meta": {}})
    )
    assert asyncio.run(_transform(tmp_path)) == output


@respx.mock
def test_503_is_gpu_unavailable(tmp_path) -> None:
    respx.post(f"{TTS}/v1/transform/cast-mentions").mock(
        return_value=httpx.Response(503, json=_err("busy"))
    )
    with pytest.raises(GpuUnavailable):
        asyncio.run(_transform(tmp_path))


@respx.mock
def test_422_is_unit_failed_with_detail(tmp_path) -> None:
    respx.post(f"{TTS}/v1/transform/cast-mentions").mock(
        return_value=httpx.Response(
            422, json={"error": {"code": "validation_failed",
                                 "detail": {"reasons": ["too_long"]}}}
        )
    )
    with pytest.raises(UnitFailed) as exc:
        asyncio.run(_transform(tmp_path))
    assert "reasons" in str(exc.value)  # detail surfaced for the review UI


@pytest.mark.parametrize("code", [400, 401, 404, 413, 500])
@respx.mock
def test_bug_class_codes_raise_pipeline_bug(tmp_path, code: int) -> None:
    respx.post(f"{TTS}/v1/transform/cast-mentions").mock(
        return_value=httpx.Response(code, json=_err("bad"))
    )
    with pytest.raises(PipelineBug):
        asyncio.run(_transform(tmp_path))


@respx.mock
def test_connection_error_is_gpu_unavailable(tmp_path) -> None:
    respx.post(f"{TTS}/v1/transform/cast-mentions").mock(
        side_effect=httpx.ConnectError("refused")
    )
    with pytest.raises(GpuUnavailable):
        asyncio.run(_transform(tmp_path))


@respx.mock
def test_unload_models_happy_and_down(tmp_path) -> None:
    route = respx.post(f"{TTS}/v1/models/unload")
    route.mock(return_value=httpx.Response(200, json={"unloaded": ["qwen3:8b"]}))
    assert asyncio.run(TtsClient(_cfg(tmp_path)).unload_models()) == {
        "unloaded": ["qwen3:8b"]
    }
    route.mock(return_value=httpx.Response(503, json=_err("busy")))
    with pytest.raises(GpuUnavailable):
        asyncio.run(TtsClient(_cfg(tmp_path)).unload_models("qwen3:8b"))


@respx.mock
def test_health_happy_and_down(tmp_path) -> None:
    route = respx.get(f"{TTS}/health")
    route.mock(return_value=httpx.Response(200, json={"status": "ok"}))
    assert asyncio.run(TtsClient(_cfg(tmp_path)).health())["status"] == "ok"
    route.mock(return_value=httpx.Response(503))
    with pytest.raises(GpuUnavailable):
        asyncio.run(TtsClient(_cfg(tmp_path)).health())


def test_missing_tts_url_is_a_bug(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    object.__setattr__(cfg, "tts_url", None)
    with pytest.raises(PipelineBug):
        TtsClient(cfg)
