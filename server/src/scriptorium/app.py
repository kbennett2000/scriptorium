"""Scriptorium server application (FastAPI).

Cycle S1 exposes exactly one endpoint, ``GET /health``. Later cycles add the
admin, library, and sync API groups and the job runner. ``/health`` must never
return 500: unreachable GPU services degrade the reported status rather than
erroring (DESIGN §11.1).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from fastapi import FastAPI

from .config import Config, load_config

_PROBE_TIMEOUT_S = 2.0

app = FastAPI(title="scriptorium", version="0.1.0")


async def _probe(url: str | None) -> dict[str, bool]:
    """Probe a GPU service's /health with a short timeout.

    Never raises: any failure (unset URL, timeout, connection error, non-2xx)
    reports reachable=False.
    """
    if not url:
        return {"configured": False, "reachable": False}
    endpoint = url.rstrip("/") + "/health"
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as client:
            resp = await client.get(endpoint)
        return {"configured": True, "reachable": resp.is_success}
    except Exception:
        return {"configured": True, "reachable": False}


def _jobs_summary(cfg: Config) -> dict[str, Any]:
    """Summarize jobs on disk. Best-effort; missing dir yields a zeroed summary."""
    by_state: dict[str, int] = {}
    total = 0
    try:
        if cfg.jobs_dir.is_dir():
            for path in cfg.jobs_dir.glob("*.json"):
                total += 1
                try:
                    with path.open(encoding="utf-8") as fh:
                        state = json.load(fh).get("state", "unknown")
                except Exception:
                    state = "unreadable"
                by_state[state] = by_state.get(state, 0) + 1
    except Exception:
        # Never let a jobs-dir problem break /health.
        return {"total": 0, "by_state": {}}
    return {"total": total, "by_state": by_state}


@app.get("/health")
async def health() -> dict[str, Any]:
    """Report server liveness, GPU-service reachability, and a jobs summary.

    Overall status is 'degraded' whenever any GPU service is unreachable, and
    'ok' only when both are reachable. This handler never raises.
    """
    try:
        cfg = load_config()
        tts = await _probe(cfg.tts_url)
        imagegen = await _probe(cfg.imagegen_url)
        jobs = _jobs_summary(cfg)
        healthy = tts["reachable"] and imagegen["reachable"]
        return {
            "status": "ok" if healthy else "degraded",
            "services": {"tts": tts, "imagegen": imagegen},
            "jobs": jobs,
        }
    except Exception as exc:  # pragma: no cover - defensive: /health never 500s
        return {
            "status": "degraded",
            "services": {
                "tts": {"configured": False, "reachable": False},
                "imagegen": {"configured": False, "reachable": False},
            },
            "jobs": {"total": 0, "by_state": {}},
            "error": type(exc).__name__,
        }
