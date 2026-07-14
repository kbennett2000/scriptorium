"""Runtime configuration for the scriptorium server.

All settings come from environment variables with sensible defaults, so the app
can start on a fresh box for tests without any env set. GPU/service URLs are only
contacted at runtime (never at import), and unreachable services degrade rather
than error (see app.health). Env contract per DESIGN §11 / BUILD-PLAN §0.1.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Repo root = server/src/scriptorium/config.py -> scriptorium -> src -> server -> <root>
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


@dataclass(frozen=True)
class Config:
    """Resolved server configuration."""

    data_dir: Path
    port: int
    tts_url: str | None
    imagegen_url: str | None
    gpu_mac: str | None
    gpu_wol_enabled: bool
    runner_tick_s: int
    shared_dir: Path

    @property
    def jobs_dir(self) -> Path:
        """Directory holding job JSON files (may not exist yet)."""
        return self.data_dir / "jobs"

    @property
    def work_dir(self) -> Path:
        """Scratch/provenance area for in-progress bakes (raw sources, §5.1)."""
        return self.data_dir / "work"

    @property
    def library_dir(self) -> Path:
        """Published bundles — immutable + additive (``library/{book_id}/``, §3/§4.2)."""
        return self.data_dir / "library"

    @property
    def schemas_dir(self) -> Path:
        """Directory holding the JSON Schemas (shared/schemas)."""
        return self.shared_dir / "schemas"


def load_config() -> Config:
    """Build a Config from the current environment."""
    shared_dir = Path(
        os.environ.get("SCRIPTORIUM_SHARED_DIR", str(_REPO_ROOT / "shared"))
    )
    return Config(
        data_dir=Path(os.environ.get("SCRIPTORIUM_DATA", "/var/lib/scriptorium")),
        port=_env_int("SCRIPTORIUM_PORT", 8720),
        tts_url=os.environ.get("TTS_URL") or None,
        imagegen_url=os.environ.get("IMAGEGEN_URL") or None,
        gpu_mac=os.environ.get("GPU_MAC") or None,
        gpu_wol_enabled=_env_bool("GPU_WOL_ENABLED", False),
        runner_tick_s=_env_int("RUNNER_TICK_S", 120),
        shared_dir=shared_dir,
    )
