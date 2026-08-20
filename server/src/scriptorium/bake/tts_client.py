"""Async client for the text-transform-service (TTS DESIGN §4/§8).

The TTS is the companion GPU-LLM service (separate repo). It exposes named transforms
(`POST /v1/transform/{name}`), a model-unload endpoint used before render phases, and a
never-500 `/health`. This client's whole job is the thin HTTP surface **plus** the mapping
from the TTS error taxonomy (§8) onto the three phase-control exceptions the runner
understands:

===========  =========================  ==============================================
HTTP status  TTS ``error.code``         raised → runner outcome
===========  =========================  ==============================================
503          busy / model_unavailable   :class:`GpuUnavailable` → ``waiting_gpu`` (retry)
422          validation_failed          :class:`UnitFailed` → 3× ladder → ``failed_units``
400/404/413  bad_request/…/over_budget  :class:`PipelineBug` → job ``failed`` (halt loudly)
401/500      unauthorized / internal    :class:`PipelineBug` → job ``failed``
(conn error) —                          :class:`GpuUnavailable` (service unreachable)
===========  =========================  ==============================================

The transform read timeout is ``cfg.transform_timeout_s`` (env ``TTS_TRANSFORM_TIMEOUT_S``,
default 1200s): a transform can now BLOCK on the server-side GPU-tenancy lock behind another
tenant's long render (ADR-0039), so the ceiling must clear a max render ahead of it. Health and
unload use the short ``_QUICK_TIMEOUT_S`` — ``/health`` is never lock-gated.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..config import Config
from .phases.base import GpuUnavailable, PipelineBug, UnitFailed

# Health/unload are fast; the transform ceiling is per-instance from Config (may block on the lock).
_QUICK_TIMEOUT_S = 15.0

# Status codes that mean "GPU busy / unreachable" → park on waiting_gpu (§8).
_GPU_UNAVAILABLE_STATUS = frozenset({503})
# Status codes that mean "this unit's generation failed validation" → retriable (§8).
_UNIT_FAILED_STATUS = frozenset({422})


class TtsClient:
    """Thin async wrapper over the text-transform-service endpoints."""

    def __init__(self, cfg: Config) -> None:
        if not cfg.tts_url:
            raise PipelineBug("TTS_URL is not configured")
        self._base = cfg.tts_url.rstrip("/")
        self._transform_timeout = cfg.transform_timeout_s

    async def _post(
        self, name: str, text: str, options: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """POST a transform and return the full ``{output, meta}`` response envelope.

        Maps the TTS error taxonomy onto phase-control exceptions (see module docstring).
        Connection/timeout failures are treated as 503-class (the service is unreachable).
        """
        url = f"{self._base}/v1/transform/{name}"
        body = {"text": text, "options": options or {}}
        try:
            async with httpx.AsyncClient(timeout=self._transform_timeout) as client:
                resp = await client.post(url, json=body)
        except httpx.HTTPError as exc:  # connect error, timeout, read error, …
            raise GpuUnavailable(f"TTS unreachable for {name!r}: {exc}") from exc

        if resp.is_success:
            return resp.json()
        raise _map_error(name, resp)

    async def transform(
        self, name: str, text: str, options: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Run transform ``name`` over ``text`` and return its ``output`` object."""
        return (await self._post(name, text, options))["output"]

    async def transform_with_meta(
        self, name: str, text: str, options: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Like :meth:`transform`, but also return the ``meta`` provenance block.

        P5 needs ``meta`` to surface any ``meta.warnings`` (e.g. a truncated/low-confidence
        generation) onto the job for the review gate; the per-page ``output`` still becomes the
        prompt's verbatim ``derived``. ``meta`` defaults to ``{}`` if the service omits it.
        """
        data = await self._post(name, text, options)
        return data["output"], data.get("meta", {})

    async def unload_models(self, model: str | None = None) -> dict[str, Any]:
        """Unload TTS models (``POST /v1/models/unload``) — the pre-render GPU handoff.

        Used by the render phase (P7/S10) to free the GPU before SDXL. A failure means
        the GPU service is not in a usable state → :class:`GpuUnavailable`.
        """
        url = f"{self._base}/v1/models/unload"
        body: dict[str, Any] = {"model": model} if model else {}
        try:
            async with httpx.AsyncClient(timeout=_QUICK_TIMEOUT_S) as client:
                resp = await client.post(url, json=body)
        except httpx.HTTPError as exc:
            raise GpuUnavailable(f"TTS unreachable for unload: {exc}") from exc
        if resp.is_success:
            return resp.json()
        raise _map_error("models/unload", resp)

    async def health(self) -> dict[str, Any]:
        """Return the TTS ``/health`` document. Raises :class:`GpuUnavailable` if down.

        (The runner's own ``default_gpu_gate`` probes ``/health`` directly for its GPU
        gate; this method is for callers that want the full status document.)
        """
        url = f"{self._base}/health"
        try:
            async with httpx.AsyncClient(timeout=_QUICK_TIMEOUT_S) as client:
                resp = await client.get(url)
        except httpx.HTTPError as exc:
            raise GpuUnavailable(f"TTS health unreachable: {exc}") from exc
        if resp.is_success:
            return resp.json()
        raise GpuUnavailable(f"TTS health returned {resp.status_code}")


def _map_error(name: str, resp: httpx.Response) -> Exception:
    """Translate a non-2xx TTS response into a phase-control exception (§8)."""
    status = resp.status_code
    detail = _error_detail(resp)
    if status in _GPU_UNAVAILABLE_STATUS:
        return GpuUnavailable(f"{name}: TTS 503 {detail}")
    if status in _UNIT_FAILED_STATUS or status >= 500:
        # 422 = this unit's generation failed validation; 5xx = a transient server-side fault
        # (e.g. the LLM emitted a character the service choked on). Both are per-unit and
        # retriable via the ladder — a single hiccup on one page must NEVER kill an
        # unattended, hundreds-of-pages bake. Exhausting the ladder records the unit in
        # ``failed_units`` and the bake continues.
        return UnitFailed(f"{name}: TTS {status} {detail}")
    # 400/401/404/413 and other 4xx: a real client-side bug (bad request shape, unknown
    # transform, oversized payload) that won't fix itself → halt loudly.
    return PipelineBug(f"{name}: TTS {status} {detail}")


def _error_detail(resp: httpx.Response) -> str:
    """Best-effort extraction of the ``error`` object from a TTS error body."""
    try:
        return str(resp.json().get("error", resp.text))
    except ValueError:
        return resp.text
