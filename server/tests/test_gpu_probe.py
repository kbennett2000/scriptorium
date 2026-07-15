"""The best-effort GPU/CPU probe behind the admin ``/gpu`` indicator.

Pure parsing tests over canned ``nvidia-smi`` / ``ollama ps`` output (monkeypatching ``_run``), plus
the graceful-degradation path when the binaries are absent. No real subprocesses.
"""

from __future__ import annotations

from scriptorium import gpu_probe

_NVIDIA = "77, 7108, 12227\n"
_OLLAMA_GPU = (
    "NAME          ID              SIZE      PROCESSOR    CONTEXT    UNTIL\n"
    "qwen3.5:9b    6488c96fa5fa    6.2 GB    100% GPU     3324       4 minutes from now\n"
)
_OLLAMA_CPU = (
    "NAME          ID              SIZE      PROCESSOR         CONTEXT    UNTIL\n"
    "qwen3.5:9b    6488c96fa5fa    6.2 GB    98%/2% CPU/GPU    3324       4 minutes from now\n"
)
_OLLAMA_EMPTY = "NAME    ID    SIZE    PROCESSOR    CONTEXT    UNTIL\n"


def _fake_run(nvidia: str | None, ollama: str | None):
    def run(argv):
        if argv and argv[0] == "nvidia-smi":
            return nvidia
        if argv and argv[0] == "ollama":
            return ollama
        return None
    return run


def test_text_model_on_gpu(monkeypatch) -> None:
    monkeypatch.setattr(gpu_probe, "_run", _fake_run(_NVIDIA, _OLLAMA_GPU))
    out = gpu_probe.probe_gpu()
    assert out["summary"] == "gpu"
    assert out["text_model"] == {"loaded": True, "name": "qwen3.5:9b", "processor": "gpu"}
    assert out["gpu"] == {"present": True, "util_percent": 77,
                          "mem_used_mib": 7108, "mem_total_mib": 12227}


def test_text_model_spilled_to_cpu_is_flagged(monkeypatch) -> None:
    monkeypatch.setattr(gpu_probe, "_run", _fake_run("1, 8900, 12227\n", _OLLAMA_CPU))
    out = gpu_probe.probe_gpu()
    assert out["summary"] == "cpu"  # the spill we want the badge to warn about
    assert out["text_model"]["processor"] == "cpu"


def test_no_model_loaded_but_card_busy_reads_gpu(monkeypatch) -> None:
    # A render is running: no LLM loaded, card busy → "gpu".
    monkeypatch.setattr(gpu_probe, "_run", _fake_run("95, 8000, 12227\n", _OLLAMA_EMPTY))
    out = gpu_probe.probe_gpu()
    assert out["text_model"]["loaded"] is False
    assert out["summary"] == "gpu"


def test_idle_when_nothing_loaded_and_card_quiet(monkeypatch) -> None:
    monkeypatch.setattr(gpu_probe, "_run", _fake_run("2, 500, 12227\n", _OLLAMA_EMPTY))
    assert gpu_probe.probe_gpu()["summary"] == "idle"


def test_missing_binaries_degrade_to_unknown(monkeypatch) -> None:
    monkeypatch.setattr(gpu_probe, "_run", _fake_run(None, None))
    out = gpu_probe.probe_gpu()
    assert out["summary"] == "unknown"
    assert out["gpu"]["present"] is False
    assert out["text_model"]["loaded"] is None


def test_endpoint_never_500s(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from scriptorium.app import app
    monkeypatch.setattr(gpu_probe, "_run", _fake_run(None, None))
    r = TestClient(app).get("/api/admin/gpu")
    assert r.status_code == 200
    assert set(r.json()) == {"gpu", "text_model", "summary"}
