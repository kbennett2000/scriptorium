"""Config env-parsing for the lock-tolerant GPU-service timeouts (ADR-0039).

The transform / generate / animate read timeouts moved to Config so a call that now BLOCKS on the
server-side GPU-tenancy lock (queued behind a long render) can wait it out instead of timing out and
churning ``waiting_gpu``. These assert the defaults, the env overrides, and that the values actually
reach the two clients built from Config.
"""

from __future__ import annotations

from scriptorium.bake.tts_client import TtsClient
from scriptorium.config import load_config
from scriptorium.render.imagegen import RealImagegenClient

_TIMEOUT_ENVS = (
    "TTS_TRANSFORM_TIMEOUT_S",
    "IMAGEGEN_GENERATE_TIMEOUT_S",
    "IMAGEGEN_ANIMATE_TIMEOUT_S",
)


def _clear(monkeypatch) -> None:
    for name in _TIMEOUT_ENVS:
        monkeypatch.delenv(name, raising=False)


def test_timeouts_default_high_enough_to_clear_a_long_render(monkeypatch) -> None:
    _clear(monkeypatch)
    cfg = load_config()
    # Generous by default: must outlast a max render / video (~20 min) queued ahead on the lock.
    assert cfg.transform_timeout_s == 1200.0
    assert cfg.generate_timeout_s == 1200.0
    assert cfg.animate_timeout_s == 1200.0


def test_timeouts_are_env_overridable(monkeypatch) -> None:
    monkeypatch.setenv("TTS_TRANSFORM_TIMEOUT_S", "30")
    monkeypatch.setenv("IMAGEGEN_GENERATE_TIMEOUT_S", "45.5")
    monkeypatch.setenv("IMAGEGEN_ANIMATE_TIMEOUT_S", "1800")
    cfg = load_config()
    assert cfg.transform_timeout_s == 30.0
    assert cfg.generate_timeout_s == 45.5
    assert cfg.animate_timeout_s == 1800.0


def test_timeout_config_reaches_the_clients(monkeypatch) -> None:
    monkeypatch.setenv("TTS_URL", "http://tts.test:8712")
    monkeypatch.setenv("IMAGEGEN_URL", "http://imagegen.test:8189")
    monkeypatch.setenv("TTS_TRANSFORM_TIMEOUT_S", "111")
    monkeypatch.setenv("IMAGEGEN_GENERATE_TIMEOUT_S", "222")
    monkeypatch.setenv("IMAGEGEN_ANIMATE_TIMEOUT_S", "333")
    cfg = load_config()

    assert TtsClient(cfg)._transform_timeout == 111.0
    client = RealImagegenClient(cfg)
    assert client._generate_timeout == 222.0
    assert client._animate_timeout == 333.0
