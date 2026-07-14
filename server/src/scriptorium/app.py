"""Scriptorium server application (FastAPI).

Cycle S1 exposes exactly one endpoint, ``GET /health``. Later cycles add the
admin, library, and sync API groups and the job runner. ``/health`` must never
return 500: unreachable GPU services degrade the reported status rather than
erroring (DESIGN §11.1).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import FastAPI

from .bake.api import router as admin_router
from .bake.phases.p1_mentions import CastMentions, MentionsEnter
from .bake.phases.p2_cast import CastCanonicalize, CastReduce
from .bake.phases.p3_ledger import LedgerEnter, LedgerScenes
from .bake.phases.p4_select import P4Select
from .bake.phases.p5_prompts import PromptsDerive, PromptsEnter
from .bake.phases.p7_render_stub import RenderStub
from .bake.review_api import router as review_router
from .bake.runner import Runner
from .config import Config, load_config

# The bake pipeline, keyed by ``from_state`` inside the runner. S5 registered P1 (mentions)
# and P2 (reduce + canonicalize); S6 appends P3 (scene ledger); S7 appends P4 (selection);
# S8 appends P5 (prompt derivation). ``MentionsEnter`` / ``CastReduce`` / ``LedgerEnter`` /
# ``PromptsEnter`` are the CPU steps that move a job onto the ``*_running`` GPU states P1/P2b/
# P3/P5 sit on; ``P4Select`` is the one pure rest→rest CPU phase (``ledger_done → selected``),
# so it needs no such enter step. A job rests at ``prompts_draft`` for human review; the review
# gate's ``approve`` endpoint (S9a) advances it to ``approved``. ``RenderStub`` (S9a) is the demo
# P7: it renders FakeImagegen placeholders (``approved → rendering``) and the job rests at
# ``rendering`` — S10 replaces it with the real GPU render + publish.
BAKE_PIPELINE = [
    MentionsEnter(),
    CastMentions(),
    CastReduce(),
    CastCanonicalize(),
    LedgerEnter(),
    LedgerScenes(),
    P4Select(),
    PromptsEnter(),
    PromptsDerive(),
    RenderStub(),
]

_PROBE_TIMEOUT_S = 2.0


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start the single bake worker for the app's lifetime (DESIGN §11.2).

    Exactly one :class:`Runner` task runs — this is what makes the single-worker /
    GPU-exclusivity guarantee structural. The pipeline runs P0 (inline in the admin
    endpoint) then P1→P2→P3→P4→P5 here; a started job rests at ``prompts_draft`` for human
    review. The review gate's ``approve`` (S9a) advances it to ``approved``, then the P7
    ``RenderStub`` renders FakeImagegen placeholders and the job rests at ``rendering`` (publish
    is S10). Plain ``TestClient(app)`` (no context manager) does not trigger lifespan, so
    endpoint tests never spin the worker.
    """
    runner = Runner(load_config(), pipeline=BAKE_PIPELINE)
    app.state.runner = runner
    task = asyncio.create_task(runner.run_forever())
    try:
        yield
    finally:
        runner.stop()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="scriptorium", version="0.1.0", lifespan=lifespan)
app.include_router(admin_router)
app.include_router(review_router)


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
