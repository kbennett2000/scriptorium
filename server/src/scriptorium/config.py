"""Runtime configuration for the scriptorium server.

All settings come from environment variables with sensible defaults, so the app
can start on a fresh box for tests without any env set. GPU/service URLs are only
contacted at runtime (never at import), and unreachable services degrade rather
than error (see app.health). Env contract per DESIGN §11 / BUILD-PLAN §0.1.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
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
    # When true the runner auto-approves a job resting at ``prompts_draft`` instead of waiting
    # for the human review gate (ADR-0015). Default false preserves invariant #4 ("no plate
    # rendered before approval") and every test; the single-user LAN dev box opts in via
    # ``AUTO_APPROVE=1``.
    auto_approve: bool = False
    # When true a freshly-ingested job is marked ``started`` immediately, so the runner advances it
    # without a human clicking Start (ADR-0020). Default false preserves the pre-P1 chapter-edit
    # window and every test; the single-user LAN dev box opts in via ``AUTO_START=1``. Pairs with
    # ``AUTO_APPROVE`` for a full unattended "kick off → wake to a done book" run.
    auto_start: bool = False
    # Base URL of the Gutendex catalog API (book search + Gutenberg metadata). Defaults to the
    # public instance; set ``GUTENDEX_URL`` to a self-hosted LAN instance. Both call sites still
    # fall back to public ``gutendex.com`` when the primary errors or returns no match.
    gutendex_url: str = "https://gutendex.com"
    # Which image-generation backend the render phases use (ADR-0038).
    # ``"local"`` is the imagegen-service on the GPU box at ``imagegen_url`` and is
    # the default, so an existing deployment is unchanged. ``"runpod"`` sends each
    # plate to a Runpod serverless endpoint instead, which is what makes the
    # fan-out below worth anything: the local service is one ComfyUI on one card
    # and serialises regardless.
    render_backend: str = "local"
    # The Runpod serverless endpoint id renders go to when ``render_backend`` is
    # ``"runpod"``. Unset is a configuration error rather than a fallback: silently
    # rendering somewhere other than where the operator asked is exactly the class
    # of surprise this switch exists to avoid.
    runpod_endpoint_id: str | None = None
    # How many plates may be in flight at once. Forced to 1 on the local backend
    # (see :func:`effective_render_concurrency`), so the home path is unchanged.
    render_concurrency: int = 4
    # The GPU model the operator expects renders to land on, e.g.
    # ``"NVIDIA GeForce RTX 4090"``. An assertion, not a request: the card is
    # pinned where the endpoint is declared, and a serverless pool can substitute
    # a different card of the same VRAM tier without saying so. When set, a render
    # whose reported card does not contain this string logs a warning. ``None``
    # disables the check.
    render_card: str | None = None
    # Built SPA dirs for the two static mounts (S11). Defaulted so tests that
    # construct Config directly need not supply them; load_config sets them from env.
    reader_dist: Path = field(default_factory=lambda: _REPO_ROOT / "reader" / "dist")
    admin_dist: Path = field(default_factory=lambda: _REPO_ROOT / "admin-ui" / "dist")

    @property
    def effective_render_concurrency(self) -> int:
        """Plates in flight, clamped to what the configured backend can actually use.

        The local backend is pinned to 1 no matter what ``RENDER_CONCURRENCY`` says.
        imagegen-service is concurrency-safe at the HTTP layer but proxies a single
        ComfyUI on a single GPU, which serialises the work anyway — so fanning out
        there buys no speed, risks the service's 300 s generate budget on the plates
        that end up last in the queue, and destroys the render-timing attribution
        that pairs ComfyUI log lines to plates in bake order.

        Fan-out pays only against a pool of workers, which is what the ``runpod``
        backend is.
        """
        if self.render_backend != "runpod":
            return 1
        return max(1, self.render_concurrency)

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

    @property
    def sync_dir(self) -> Path:
        """Root of the mutable sync layer — annotations, positions, and their
        versioned backups (``sync/{annotations,positions,annotations-backups}/``,
        DESIGN §12). Outside ``library/`` because sync docs are the one thing that
        changes after publish."""
        return self.data_dir / "sync"

    @property
    def artsets_dir(self) -> Path:
        """Root of per-user picture "sets" (``artsets/{user}/{book}/{set_id}/``, DESIGN §8,
        ADR-0014). Private per household profile and additive — outside ``library/`` so the
        immutable published bundle is never touched. Holds each set's images + manifest."""
        return self.data_dir / "artsets"

    @property
    def users_file(self) -> Path:
        """Household profiles file (``users.json``, DESIGN §14). May be absent on a
        fresh box — the users loader falls back to a committed dev sample."""
        return self.data_dir / "users.json"


def load_config() -> Config:
    """Build a Config from the current environment."""
    shared_dir = Path(
        os.environ.get("SCRIPTORIUM_SHARED_DIR", str(_REPO_ROOT / "shared"))
    )
    reader_dist = Path(
        os.environ.get("SCRIPTORIUM_READER_DIST", str(_REPO_ROOT / "reader" / "dist"))
    )
    admin_dist = Path(
        os.environ.get("SCRIPTORIUM_ADMIN_DIST", str(_REPO_ROOT / "admin-ui" / "dist"))
    )
    return Config(
        data_dir=Path(os.environ.get("SCRIPTORIUM_DATA", "/var/lib/scriptorium")),
        port=_env_int("SCRIPTORIUM_PORT", 8720),
        tts_url=os.environ.get("TTS_URL") or None,
        imagegen_url=os.environ.get("IMAGEGEN_URL") or None,
        gpu_mac=os.environ.get("GPU_MAC") or None,
        gpu_wol_enabled=_env_bool("GPU_WOL_ENABLED", False),
        runner_tick_s=_env_int("RUNNER_TICK_S", 5),
        auto_approve=_env_bool("AUTO_APPROVE", False),
        auto_start=_env_bool("AUTO_START", False),
        gutendex_url=os.environ.get("GUTENDEX_URL") or "https://gutendex.com",
        render_backend=(os.environ.get("RENDER_BACKEND") or "local").strip().lower(),
        runpod_endpoint_id=os.environ.get("RUNPOD_ENDPOINT_ID") or None,
        render_concurrency=_env_int("RENDER_CONCURRENCY", 4),
        render_card=os.environ.get("RENDER_CARD") or None,
        shared_dir=shared_dir,
        reader_dist=reader_dist,
        admin_dist=admin_dist,
    )
