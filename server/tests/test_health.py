"""/health tests: reports ok when both GPU services are reachable, degraded (not
500) when they are down (BUILD-PLAN S1 acceptance; DESIGN §11.1)."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from scriptorium.app import app

TTS = "http://tts.test:8712"
IMAGEGEN = "http://imagegen.test:9000"


@pytest.fixture
def client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setenv("TTS_URL", TTS)
    monkeypatch.setenv("IMAGEGEN_URL", IMAGEGEN)
    monkeypatch.setenv("SCRIPTORIUM_DATA", str(tmp_path))
    return TestClient(app)


@respx.mock
def test_health_ok_when_both_up(client: TestClient) -> None:
    respx.get(f"{TTS}/health").mock(return_value=httpx.Response(200))
    respx.get(f"{IMAGEGEN}/health").mock(return_value=httpx.Response(200))

    resp = client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["services"]["tts"] == {"configured": True, "reachable": True}
    assert body["services"]["imagegen"] == {"configured": True, "reachable": True}
    assert body["jobs"] == {"total": 0, "by_state": {}}


@respx.mock
def test_health_degraded_when_both_down(client: TestClient) -> None:
    respx.get(f"{TTS}/health").mock(side_effect=httpx.ConnectError("down"))
    respx.get(f"{IMAGEGEN}/health").mock(side_effect=httpx.ConnectError("down"))

    resp = client.get("/health")

    # The load-bearing assertion: degraded, never 500.
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["services"]["tts"]["reachable"] is False
    assert body["services"]["imagegen"]["reachable"] is False


@respx.mock
def test_health_degraded_when_one_down(client: TestClient) -> None:
    respx.get(f"{TTS}/health").mock(return_value=httpx.Response(200))
    respx.get(f"{IMAGEGEN}/health").mock(return_value=httpx.Response(503))

    resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.json()["status"] == "degraded"


def test_health_degraded_when_unconfigured(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("TTS_URL", raising=False)
    monkeypatch.delenv("IMAGEGEN_URL", raising=False)
    monkeypatch.setenv("SCRIPTORIUM_DATA", str(tmp_path))
    resp = TestClient(app).get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["services"]["tts"]["configured"] is False
