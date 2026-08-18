"""Imagegen client protocol, the real HTTP client, and a deterministic fake (DESIGN §10, ADR-0011).

The bake's render phase (P7) talks to an image-generation service only through the
:class:`ImagegenClient` protocol. Two implementations:

- :class:`RealImagegenClient` — the S10 HTTP binding to imagegen-service (``POST /generate`` →
  raw PNG bytes, ``GET /health`` → ``{comfyuiReachable}``), documented in
  ``docs/adr/0011-imagegen-api.md``. It maps the service's error taxonomy onto the phase-control
  exceptions the runner understands (503/connection → ``GpuUnavailable``, 422 → ``UnitFailed``,
  everything else → ``PipelineBug``), mirroring :class:`~scriptorium.bake.tts_client.TtsClient`.
- :class:`FakeImagegen` — the offline stand-in used by every test and by the render e2e: a
  **deterministic** placeholder PNG with the request's hash burned into the pixels, no GPU/network.
  Same ``(prompt, size, seed)`` in → byte-identical PNG out, which lets tests assert determinism
  without asserting image content (CLAUDE.md: never assert exact image content).

Style rides in ``prompt``/``negative`` *and*, optionally, in the imagegen-service ``style`` preset:
passing ``style`` (an imagegen preset name like ``"oil painting"``) makes the service apply that
style's LoRA (ADR-0013). ``style=None`` (the default) is the original prompt-only, byte-identical
behaviour. ``checkpoint`` (ADR-0030) is an orthogonal axis: the base SDXL model to render with (a
ComfyUI ``ckpt_name`` from the service's ``/health`` ``checkpoints`` list); ``None`` leaves the
service on its configured default, byte-identical to the pre-ADR-0030 client. Sizes come from the
caller (P7): plate/cover 832×1216, portrait 1024×1024.
imagegen-service honours ``width``/``height`` only once the S10a size PR (this cycle) is
merged+deployed; older builds ignore them (fixed 1024²).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import logging
import time
import tomllib
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import httpx
from PIL import Image, ImageDraw, ImageFont

from ..bake.phases.base import GpuUnavailable, PipelineBug, UnitFailed
from ..config import Config

_log = logging.getLogger(__name__)

# DESIGN §10 render sizes (plate/cover); portraits are 1024×1024. The stub renders every plate at
# the plate size — the real P7 (S10) sizes per asset. Kept here so the fake has a sensible default.
PLATE_SIZE: tuple[int, int] = (832, 1216)


@runtime_checkable
class ImagegenClient(Protocol):
    """The image-generation surface P7 depends on (DESIGN §10).

    ``txt2img`` returns PNG bytes; ``health`` reports reachability (used by the GPU gate in the
    real S10 phase). ``style`` is an optional imagegen-service preset name (applies a LoRA);
    ``None`` keeps the prompt-only behaviour (ADR-0013).
    """

    async def txt2img(
        self,
        prompt: str,
        negative: str = "",
        width: int = PLATE_SIZE[0],
        height: int = PLATE_SIZE[1],
        seed: int | None = None,
        style: str | None = None,
        checkpoint: str | None = None,
        references: list[bytes] | None = None,
        reference_strength: float | None = None,
        reference_start: float | None = None,
        init_image: bytes | None = None,
        denoise: float | None = None,
        quality: str | None = None,
    ) -> bytes:
        """Render ``prompt`` to PNG bytes at ``width``×``height``, optionally under ``style``.

        ``checkpoint`` selects the base SDXL model (a ComfyUI ``ckpt_name``); ``None`` uses the
        service's configured default (ADR-0030).

        ``references`` is an optional list of reference-image PNG bytes (a character's portrait) fed
        to the service as image-prompt conditioning for character consistency (ADR-0023). ``None``
        (the default) keeps the prompt-only, byte-identical behaviour.

        ``reference_strength`` (IP-Adapter weight) and ``reference_start`` (the fraction of the
        denoising schedule that runs before identity is injected) tune that conditioning per plate;
        ``None`` leaves the service's own defaults in place (ADR-0028).

        ``init_image`` is optional img2img starting-image PNG bytes: the service repaints it toward
        the prompt instead of starting from noise. ``denoise`` (0, 1] is the change amount (lower =
        closer to the starting image). Both ``None`` (the default) keeps the txt2img,
        byte-identical behaviour (the post-publish picture editor uses these; §post-publish edits).

        ``quality`` is the service's quality tier (``"fast"``/``"standard"``/``"high"``); ``None``
        (the default) leaves the service on its configured default, byte-identical to the pre-edit
        request. Exposed to the post-publish picture editor for full imagegen-harness parity.
        """
        ...

    async def health(self) -> bool:
        """True iff the service is reachable."""
        ...

    async def animate(
        self,
        image: bytes,
        prompt: str,
        *,
        model: str | None = None,
        negative: str = "",
        seed: int | None = None,
        frames: int | None = None,
        fps: int | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes:
        """Animate a still into a short clip: ``POST /animate`` → raw mp4 bytes (WAN 2.2, ADR-0037).

        ``image`` is the PNG start-frame bytes; ``prompt`` is the motion prompt ("how it should
        move"). ``model`` is the service's animate model wire id (``"wan-5b"`` / ``"remix-14b"``);
        ``None`` uses the service default. ``frames``/``fps``/``width``/``height``/``seed`` are
        forwarded only when set, so an unset field uses the service default. Renders take minutes —
        the caller must allow a generous read timeout. Maps 503/conn → ``GpuUnavailable`` (the same
        gate txt2img uses), so a busy/unready GPU parks rather than crashing.
        """
        ...

    async def video_health(self) -> dict[str, Any]:
        """The installed animate models for the editor's picker + readiness gate (ADR-0037).

        Returns ``{"models": [wire_id, …], "reachable": bool}`` — a subset of ``{"wan-5b",
        "remix-14b"}`` per the service's ``/health`` ``wan.ready``/``remix.ready`` flags. Any
        failure yields an empty, unreachable result (never raises), so the editor hides the video
        section rather than offering a call that would 503.
        """
        ...


# imagegen-service is a ComfyUI proxy: /generate can load an SDXL model on the first call, so the
# generate timeout is generous (the service's own tier budget tops out at 300s); health is quick.
# /animate renders a multi-second clip and, on the first job after an image job, pauses to swap the
# GPU model set — minutes — so its budget mirrors the service's own 20-minute animate poll budget.
_GENERATE_TIMEOUT_S = 300.0
_HEALTH_TIMEOUT_S = 15.0
_ANIMATE_TIMEOUT_S = 1200.0


class RealImagegenClient:
    """HTTP binding to imagegen-service (ADR-0011). Raw PNG out; errors → phase-control exceptions.

    Built from :class:`~scriptorium.config.Config`; ``imagegen_url`` may be unset (nothing contacts
    a service at import). When unset, :meth:`health` is ``False`` and :meth:`txt2img` raises
    :class:`GpuUnavailable`, so the render phase parks on ``waiting_gpu`` instead of crashing.
    """

    def __init__(self, cfg: Config) -> None:
        self._base = cfg.imagegen_url.rstrip("/") if cfg.imagegen_url else None

    async def txt2img(
        self,
        prompt: str,
        negative: str = "",
        width: int = PLATE_SIZE[0],
        height: int = PLATE_SIZE[1],
        seed: int | None = None,
        style: str | None = None,
        checkpoint: str | None = None,
        references: list[bytes] | None = None,
        reference_strength: float | None = None,
        reference_start: float | None = None,
        init_image: bytes | None = None,
        denoise: float | None = None,
        quality: str | None = None,
    ) -> bytes:
        """``POST /generate`` → PNG bytes. Maps 503/conn → GpuUnavailable, 422 → UnitFailed."""
        if self._base is None:
            raise GpuUnavailable("IMAGEGEN_URL is not configured")
        body: dict[str, Any] = {
            "prompt": prompt,
            "negativePrompt": negative,
            "width": width,
            "height": height,
        }
        if seed is not None:
            body["seed"] = seed
        # Only forward `quality` when set, so a default-tier request stays byte-identical to the
        # pre-edit client (the service falls back to its configured default tier).
        if quality is not None:
            body["quality"] = quality
        # Only forward `style` when set, so prompt-only styles produce byte-identical requests
        # to the pre-ADR-0013 client (the service applies the named preset's LoRA; ADR-0011).
        if style is not None:
            body["style"] = style
        # Only forward `checkpoint` when set: the service falls back to its configured default
        # (precedence request > config > workflow), so an unset model is byte-identical to the
        # pre-ADR-0030 request. The service/ComfyUI is the authority on which names exist.
        if checkpoint is not None:
            body["checkpoint"] = checkpoint
        # Only forward `references` when set: the service switches to the IP-Adapter workflow and
        # conditions on these portrait images (ADR-0023). Absent → prompt-only, byte-identical.
        if references:
            body["references"] = [base64.b64encode(r).decode("ascii") for r in references]
            # Only meaningful alongside a reference; sent only when the caller overrides the
            # service default, so an unconditioned request stays byte-identical (ADR-0028).
            if reference_strength is not None:
                body["referenceStrength"] = reference_strength
            if reference_start is not None:
                body["referenceStart"] = reference_start
        # img2img: only forward when an init image is given, so a txt2img request stays
        # byte-identical to the pre-edit client (the service falls back to txt2img otherwise).
        if init_image is not None:
            body["initImage"] = base64.b64encode(init_image).decode("ascii")
            if denoise is not None:
                body["denoise"] = denoise
        url = f"{self._base}/generate"
        try:
            async with httpx.AsyncClient(timeout=_GENERATE_TIMEOUT_S) as client:
                resp = await client.post(url, json=body)
        except httpx.HTTPError as exc:  # connect error, timeout, read error, …
            raise GpuUnavailable(f"imagegen unreachable: {exc}") from exc
        if resp.is_success:
            return resp.content
        raise _map_error(resp)

    async def health(self) -> bool:
        """GET /health -> the comfyuiReachable bool; any failure yields False (never raises)."""
        if self._base is None:
            return False
        url = f"{self._base}/health"
        try:
            async with httpx.AsyncClient(timeout=_HEALTH_TIMEOUT_S) as client:
                resp = await client.get(url)
            if not resp.is_success:
                return False
            return bool(resp.json().get("comfyuiReachable", False))
        except Exception:
            return False

    async def models(self) -> dict[str, Any]:
        """GET /health → the installed base models for a picker (ADR-0030), best-effort.

        Returns ``{"models": [ckpt_name, …], "default": ckpt_name | None, "reachable": bool}``.
        The service already exposes the full ComfyUI checkpoint list under ``checkpoints`` and the
        effective default under ``checkpoint``. Any failure yields an empty, unreachable result
        (never raises) so the admin picker degrades gracefully instead of 500ing.
        """
        empty = {"models": [], "default": None, "reachable": False}
        if self._base is None:
            return empty
        try:
            async with httpx.AsyncClient(timeout=_HEALTH_TIMEOUT_S) as client:
                resp = await client.get(f"{self._base}/health")
            if not resp.is_success:
                return empty
            data = resp.json()
            models = [str(m) for m in (data.get("checkpoints") or [])]
            default = data.get("checkpoint")
            return {
                "models": models,
                "default": str(default) if default else None,
                "reachable": bool(data.get("comfyuiReachable", False)),
            }
        except Exception:
            return empty

    async def styles(self) -> dict[str, Any]:
        """GET /styles → the installed LoRA style presets for a picker (ADR-0013), best-effort.

        Returns ``{"styles": [{"name": str, "hasLora": bool}, …], "reachable": bool}``. Any failure
        yields an empty, unreachable result (never raises), so the editor's Style picker degrades to
        the local styles catalog instead of 500ing. The styles-catalog (``data/styles.json``) is
        the authority on which ids the pipeline wraps; this only surfaces what the service loaded.
        """
        empty = {"styles": [], "reachable": False}
        if self._base is None:
            return empty
        try:
            async with httpx.AsyncClient(timeout=_HEALTH_TIMEOUT_S) as client:
                resp = await client.get(f"{self._base}/styles")
            if not resp.is_success:
                return empty
            data = resp.json()
            styles = [
                {"name": str(s.get("name", "")), "hasLora": bool(s.get("hasLora", False))}
                for s in (data.get("styles") or [])
                if s.get("name")
            ]
            return {"styles": styles, "reachable": True}
        except Exception:
            return empty

    async def animate(
        self,
        image: bytes,
        prompt: str,
        *,
        model: str | None = None,
        negative: str = "",
        seed: int | None = None,
        frames: int | None = None,
        fps: int | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes:
        """``POST /animate`` → mp4 bytes. Maps 503/conn → GpuUnavailable, 422 → UnitFailed."""
        if self._base is None:
            raise GpuUnavailable("IMAGEGEN_URL is not configured")
        body: dict[str, Any] = {
            "image": base64.b64encode(image).decode("ascii"),
            "prompt": prompt,
        }
        # Forward every optional field only when set, so an unspecified knob uses the service
        # default (the service is the authority on default model/size/frames/fps).
        if negative:
            body["negativePrompt"] = negative
        if model is not None:
            body["model"] = model
        if seed is not None:
            body["seed"] = seed
        if frames is not None:
            body["frames"] = frames
        if fps is not None:
            body["fps"] = fps
        if width is not None:
            body["width"] = width
        if height is not None:
            body["height"] = height
        url = f"{self._base}/animate"
        try:
            async with httpx.AsyncClient(timeout=_ANIMATE_TIMEOUT_S) as client:
                resp = await client.post(url, json=body)
        except httpx.HTTPError as exc:  # connect error, timeout, read error, …
            raise GpuUnavailable(f"imagegen unreachable: {exc}") from exc
        if resp.is_success:
            return resp.content
        raise _map_error(resp)

    async def video_health(self) -> dict[str, Any]:
        """GET /health → installed animate models (``wan.ready``/``remix.ready``); best-effort."""
        empty = {"models": [], "reachable": False}
        if self._base is None:
            return empty
        try:
            async with httpx.AsyncClient(timeout=_HEALTH_TIMEOUT_S) as client:
                resp = await client.get(f"{self._base}/health")
            if not resp.is_success:
                return empty
            data = resp.json()
            models: list[str] = []
            if (data.get("wan") or {}).get("ready"):
                models.append("wan-5b")
            if (data.get("remix") or {}).get("ready"):
                models.append("remix-14b")
            return {"models": models, "reachable": bool(data.get("comfyuiReachable", False))}
        except Exception:
            return empty


class RunpodImagegenClient:
    """Render a plate on a Runpod serverless endpoint instead of the local GPU (ADR-0038).

    Implements the same :class:`ImagegenClient` surface, so ``render_to_spec`` and both
    render phases are unchanged — only which object they are handed differs.

    Three things about the wire shape are worth knowing:

    - **``/run`` then poll ``/status``, never ``/runsync``.** ``/runsync`` gives up at
      60 s, and a cold start behind a 17.66 GB image pull does not fit in that. A warm
      render is ~4.4 s; a cold one measured 431 s wall, almost all of it image pull.
    - **The PNG travels base64 in the response body**, and the IP-Adapter reference
      portrait travels base64 in the request. Deliberate: it means no character artwork
      is ever baked into the container or the registry.
    - **``style`` and ``checkpoint`` are not sent.** The worker image bakes exactly one
      checkpoint (``sd_xl_base_1.0``) and applies the oil-painting LoRA whenever
      ``lora`` is true. A request for a different checkpoint cannot be honoured, so it
      raises rather than quietly rendering the wrong model.

    Transient failures retry here, inside the client, on top of — not instead of — the
    runner's per-unit ladder: a serverless pool sheds load with 429s and 5xxs that are
    not plate failures, and burning a 10/60/300 s ladder step on one is wasteful.
    """

    _BASE = "https://api.runpod.ai/v2"
    # 3 attempts, 2/5/10 s apart. Short because these are queue-level hiccups; the
    # runner's ladder is what handles anything structural.
    _RETRY_DELAYS: tuple[float, ...] = (2.0, 5.0, 10.0)
    _POLL_S = 0.5
    _SUBMIT_TIMEOUT_S = 60.0
    # Generous: this covers a cold worker pulling the image before it can render.
    _JOB_TIMEOUT_S = 900.0

    def __init__(self, cfg: Config) -> None:
        self._endpoint = getattr(cfg, "runpod_endpoint_id", None)
        self._expect_card = getattr(cfg, "render_card", None)
        self._last_echo: dict[str, Any] = {}

    @property
    def last_echo(self) -> dict[str, Any]:
        """The worker's own report of the most recent render, minus the image.

        Carries ``render_s``/``model_load_s``/``total_s``, the card name, and the
        sampler settings the graph was actually built with. P7 folds this into the
        plate's ``render.params_echo``, which is what gives per-plate timing under a
        fan-out — log-order pairing cannot attribute concurrent renders.
        """
        return dict(self._last_echo)

    def _url(self, path: str) -> str:
        if not self._endpoint:
            raise GpuUnavailable("RUNPOD_ENDPOINT_ID is not configured")
        return f"{self._BASE}/{self._endpoint}{path}"

    async def txt2img(
        self,
        prompt: str,
        negative: str = "",
        width: int = PLATE_SIZE[0],
        height: int = PLATE_SIZE[1],
        seed: int | None = None,
        style: str | None = None,
        checkpoint: str | None = None,
        references: list[bytes] | None = None,
        reference_strength: float | None = None,
        reference_start: float | None = None,
        init_image: bytes | None = None,
        denoise: float | None = None,
        quality: str | None = None,
    ) -> bytes:
        if seed is None:
            # The worker refuses a seedless request for the same reason: a plate must
            # re-render identically, and an invented seed destroys that silently.
            raise PipelineBug("runpod render requires an explicit seed")
        if checkpoint is not None:
            raise PipelineBug(
                f"runpod worker bakes one checkpoint; cannot honour {checkpoint!r}"
            )
        if init_image is not None:
            raise PipelineBug("runpod worker does not implement img2img")

        payload: dict[str, Any] = {
            "prompt": prompt,
            "negative": negative,
            "seed": seed,
            "width": width,
            "height": height,
        }
        if references:
            payload["reference_png_b64"] = base64.b64encode(references[0]).decode("ascii")
            # ADR-0028's per-plate conditioning. The worker defaults to 0.5/0.3 when
            # these are absent, which is NOT what a multi-figure plate wants — sending
            # them is the whole reason the worker grew the inputs.
            if reference_strength is not None:
                payload["reference_strength"] = reference_strength
            if reference_start is not None:
                payload["reference_start"] = reference_start

        output = await self._run_job({"input": payload})

        if not isinstance(output, dict):
            raise UnitFailed(f"runpod worker returned {type(output).__name__}, expected object")
        if "error" in output:
            # The worker reports its own failures inside a COMPLETED job, so a
            # successful HTTP status is not a successful render.
            raise UnitFailed(f"runpod worker: {output['error']}")
        if "image_png_b64" not in output:
            raise UnitFailed("runpod worker returned no image")

        echo = {k: v for k, v in output.items() if k != "image_png_b64"}
        self._last_echo = echo
        card = str(echo.get("gpu") or "")
        if self._expect_card and self._expect_card not in card:
            # A warning, never a failure: the pixels are real and the timing is real,
            # they just came from a card the operator did not ask for. Cycle 3 measured
            # this happening silently, which is why it is checked at all.
            _log.warning(
                "render landed on %r, expected %r — timings are not comparable "
                "across cards", card or "unknown", self._expect_card,
            )
        try:
            return base64.b64decode(output["image_png_b64"])
        except (ValueError, TypeError) as exc:
            raise UnitFailed(f"runpod worker returned undecodable image: {exc}") from exc

    async def _run_job(self, body: dict[str, Any]) -> Any:
        """Submit, poll to a terminal state, return the job's ``output``."""
        job_id = await self._submit(body)
        deadline = time.monotonic() + self._JOB_TIMEOUT_S
        async with httpx.AsyncClient(timeout=self._SUBMIT_TIMEOUT_S) as client:
            while time.monotonic() < deadline:
                await asyncio.sleep(self._POLL_S)
                try:
                    resp = await client.get(
                        self._url(f"/status/{job_id}"), headers=_runpod_auth()
                    )
                except httpx.HTTPError:
                    continue  # a dropped poll is not a failed job; keep asking
                if not resp.is_success:
                    continue
                data = resp.json()
                status = data.get("status")
                if status == "COMPLETED":
                    return data.get("output")
                if status in ("FAILED", "CANCELLED", "TIMED_OUT"):
                    raise UnitFailed(f"runpod job {status}: {data.get('error') or ''}".strip())
        raise GpuUnavailable(f"runpod job {job_id} did not finish in {self._JOB_TIMEOUT_S:.0f}s")

    async def _submit(self, body: dict[str, Any]) -> str:
        """POST /run with a bounded retry on transient failures."""
        last: Exception | None = None
        for attempt in range(len(self._RETRY_DELAYS) + 1):
            try:
                async with httpx.AsyncClient(timeout=self._SUBMIT_TIMEOUT_S) as client:
                    resp = await client.post(
                        self._url("/run"), json=body, headers=_runpod_auth()
                    )
                if resp.is_success:
                    job_id = resp.json().get("id")
                    if job_id:
                        return str(job_id)
                    last = UnitFailed("runpod /run returned no job id")
                elif resp.status_code == 429 or resp.status_code >= 500:
                    last = GpuUnavailable(f"runpod /run {resp.status_code}")
                elif resp.status_code in (401, 403):
                    # Never retried: a bad credential will still be bad in 10 seconds,
                    # and retrying an auth failure just delays a clear error.
                    raise PipelineBug(f"runpod /run {resp.status_code}: check the API key")
                else:
                    raise PipelineBug(f"runpod /run {resp.status_code}")
            except httpx.HTTPError as exc:
                last = GpuUnavailable(f"runpod unreachable: {exc}")
            if attempt < len(self._RETRY_DELAYS):
                await asyncio.sleep(self._RETRY_DELAYS[attempt])
        raise last or GpuUnavailable("runpod /run failed")

    async def health(self) -> bool:
        """GET /health. True iff the endpoint answers; never raises."""
        if not self._endpoint:
            return False
        try:
            async with httpx.AsyncClient(timeout=_HEALTH_TIMEOUT_S) as client:
                resp = await client.get(self._url("/health"), headers=_runpod_auth())
            return resp.is_success
        except Exception:
            return False

    async def models(self) -> dict[str, Any]:
        """The worker bakes exactly one checkpoint, so there is nothing to pick from."""
        return {"models": [], "default": None, "reachable": bool(self._endpoint)}

    async def styles(self) -> dict[str, Any]:
        """Style presets live in the image, not in a service catalog."""
        return {"styles": [], "reachable": bool(self._endpoint)}

    async def animate(
        self,
        image: bytes,
        prompt: str,
        *,
        model: str | None = None,
        negative: str = "",
        seed: int | None = None,
        frames: int | None = None,
        fps: int | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes:
        """Not implemented on the render worker — ADR-0037 video stays on the local service."""
        raise GpuUnavailable("runpod render backend does not implement /animate")

    async def video_health(self) -> dict[str, Any]:
        """No animate models, so the editor hides the video section rather than 503ing."""
        return {"models": [], "reachable": False}


def _runpod_auth() -> dict[str, str]:
    """Build the Bearer header, reading the key in-process and never returning it.

    The key is read from ``~/.runpod/config.toml`` here rather than taken from an
    environment variable on purpose. An env var for a long-lived credential means it
    is exported by some shell, visible in that process's environment, and typically
    typed into a history file first. Reading the file in-process keeps it out of all
    three. Both key names are accepted: ``runpodctl`` writes a top-level ``apikey``
    and ``flash`` writes ``[default].api_key`` (runpod/flash#363).

    The value is never logged, never echoed, and never stored on the client.
    """
    path = Path.home() / ".runpod" / "config.toml"
    if not path.is_file():
        raise GpuUnavailable(f"no Runpod credential file at {path}")
    try:
        with path.open("rb") as fh:
            conf = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise GpuUnavailable(f"cannot read {path}: {exc}") from exc
    for value in (conf.get("default", {}).get("api_key"), conf.get("apikey")):
        if isinstance(value, str) and value.strip():
            return {"Authorization": f"Bearer {value.strip()}"}
    raise GpuUnavailable(f"{path} has neither `[default].api_key` nor `apikey`")


def build_imagegen_client(cfg: Config) -> Any:
    """The configured render backend (ADR-0038). ``local`` unless asked otherwise.

    **Only the bake's render phases use this.** The remote worker implements
    ``txt2img`` and nothing else — no img2img, no ``/animate``, no checkpoint or
    style catalog — so the paths that need those keep constructing
    :class:`RealImagegenClient` directly and keep working exactly as before:

    - ``artsets/api.py`` — the post-publish picture editor (img2img, ADR-0037 video)
    - ``bake/api.py`` — the admin model picker's catalog read
    - ``bake/review_api.py`` — the review-gate regeneration
    - ``artsets/phase.py`` — per-user style-set re-illustration

    Routing those through a backend that raises on half their surface would be a
    wider change than this one is meant to be. Moving any of them is a later
    decision with its own reason, not a consequence of this switch.
    """
    if getattr(cfg, "render_backend", "local") == "runpod":
        return RunpodImagegenClient(cfg)
    return RealImagegenClient(cfg)


def _map_error(resp: httpx.Response) -> Exception:
    """Translate a non-2xx /generate response into a phase-control exception (ADR-0011).

    imagegen-service returns 503 for any ComfyUI-side failure (unreachable/timeout/rejected
    workflow) → treat as GPU-unavailable and retry; 422 for a bad request body → the plate's unit
    failed (ladder then ``failed_units``); anything else is a bug we can't retry around.
    """
    status = resp.status_code
    detail = _error_detail(resp)
    if status == 503:
        return GpuUnavailable(f"imagegen 503 {detail}")
    if status == 422:
        return UnitFailed(f"imagegen 422 {detail}")
    return PipelineBug(f"imagegen {status} {detail}")


def _error_detail(resp: httpx.Response) -> str:
    """Best-effort extraction of the ``error`` field from an imagegen JSON error body."""
    try:
        return str(resp.json().get("error", resp.text))
    except ValueError:
        return resp.text


def _digest(
    prompt: str,
    width: int,
    height: int,
    seed: int | None,
    style: str | None = None,
    checkpoint: str | None = None,
    references: list[bytes] | None = None,
    reference_strength: float | None = None,
    reference_start: float | None = None,
    init_image: bytes | None = None,
    denoise: float | None = None,
    quality: str | None = None,
) -> str:
    """A stable hex digest of the full render request (drives both color and burned-in text).

    Every optional argument is folded in only when set, so the default (``None``) yields
    byte-identical placeholders to the pre-existing fake (determinism/round-trip fixtures stay
    green), while distinct styles/models/references/conditioning produce visibly distinct stand-ins.
    """
    payload = f"{prompt}\x00{width}x{height}\x00{seed}".encode()
    if style is not None:
        payload += f"\x00{style}".encode()
    # A different base model produces different pixels, so it must change the stand-in too;
    # folded only when set, so an unset model stays byte-identical to the pre-ADR-0030 fake.
    if checkpoint is not None:
        payload += f"\x00ckpt={checkpoint}".encode()
    if references:
        # Fold a hash of each reference's bytes (not the raw bytes) to keep the payload small.
        for ref in references:
            payload += b"\x00" + hashlib.sha256(ref).digest()
        # Conditioning strength changes the real render, so it must change the stand-in too —
        # otherwise a test could not tell a multi-figure plate's weaker anchor from a solo one.
        if reference_strength is not None:
            payload += f"\x00w={reference_strength}".encode()
        if reference_start is not None:
            payload += f"\x00s={reference_start}".encode()
    # img2img changes the real render, so the stand-in must differ too; folded only when set, so
    # a txt2img request stays byte-identical to the pre-edit fake.
    if init_image is not None:
        payload += b"\x00init=" + hashlib.sha256(init_image).digest()
        if denoise is not None:
            payload += f"\x00d={denoise}".encode()
    # A different quality tier produces different pixels, so it must change the stand-in too;
    # folded only when set, so an unset tier stays byte-identical to the pre-edit fake.
    if quality is not None:
        payload += f"\x00q={quality}".encode()
    return hashlib.sha256(payload).hexdigest()


class FakeImagegen:
    """Deterministic placeholder PNG generator (no GPU, no network).

    The PNG carries the request's hash as text on a hash-derived background, so it is visually
    distinct per prompt yet byte-reproducible. Intended for tests and the S9 render stub only.
    """

    async def txt2img(
        self,
        prompt: str,
        negative: str = "",
        width: int = PLATE_SIZE[0],
        height: int = PLATE_SIZE[1],
        seed: int | None = None,
        style: str | None = None,
        checkpoint: str | None = None,
        references: list[bytes] | None = None,
        reference_strength: float | None = None,
        reference_start: float | None = None,
        init_image: bytes | None = None,
        denoise: float | None = None,
        quality: str | None = None,
    ) -> bytes:
        return self.render(
            prompt,
            width=width,
            height=height,
            seed=seed,
            style=style,
            checkpoint=checkpoint,
            references=references,
            reference_strength=reference_strength,
            reference_start=reference_start,
            init_image=init_image,
            denoise=denoise,
            quality=quality,
        )

    async def health(self) -> bool:
        return True

    async def models(self) -> dict[str, Any]:
        """No installed models offline — the editor's model picker degrades to the current one."""
        return {"models": [], "default": None, "reachable": True}

    async def styles(self) -> dict[str, Any]:
        """No service style presets offline — the editor falls back to the local styles catalog."""
        return {"styles": [], "reachable": True}

    async def animate(
        self,
        image: bytes,
        prompt: str,
        *,
        model: str | None = None,
        negative: str = "",
        seed: int | None = None,
        frames: int | None = None,
        fps: int | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes:
        """Deterministic placeholder mp4-shaped bytes (no GPU). Same request in → same bytes out.

        Not a playable video — tests assert the request params/shape and the commit plumbing, never
        the clip content (CLAUDE.md). The start-frame bytes and every set param fold into the digest
        so distinct requests yield distinct stand-ins.
        """
        payload = f"{prompt}\x00{model}\x00{negative}\x00{seed}\x00{frames}\x00{fps}".encode()
        payload += f"\x00{width}x{height}".encode() + b"\x00" + hashlib.sha256(image).digest()
        digest = hashlib.sha256(payload).digest()
        # A minimal ISO-BMFF ftyp box header so contentTypeFor/callers see mp4-ish bytes, then the
        # request digest as the deterministic payload.
        return b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + digest

    async def video_health(self) -> dict[str, Any]:
        """The fake reports the fast Wan model ready, so tests exercise the video path offline."""
        return {"models": ["wan-5b"], "reachable": True}

    def render(
        self,
        prompt: str,
        *,
        width: int = PLATE_SIZE[0],
        height: int = PLATE_SIZE[1],
        seed: int | None = None,
        style: str | None = None,
        checkpoint: str | None = None,
        references: list[bytes] | None = None,
        reference_strength: float | None = None,
        reference_start: float | None = None,
        init_image: bytes | None = None,
        denoise: float | None = None,
        quality: str | None = None,
    ) -> bytes:
        """Synchronous core: deterministic placeholder PNG bytes for ``prompt``."""
        digest = _digest(
            prompt, width, height, seed, style, checkpoint,
            references, reference_strength, reference_start,
            init_image, denoise, quality,
        )
        # Background: a muted color from the digest so distinct prompts look distinct.
        bg = (int(digest[0:2], 16) // 2, int(digest[2:4], 16) // 2, int(digest[4:6], 16) // 2)
        img = Image.new("RGB", (width, height), bg)
        draw = ImageDraw.Draw(img)
        font = ImageFont.load_default()
        lines = [
            "PLACEHOLDER (FakeImagegen)",
            f"hash {digest[:16]}",
            f"{width}x{height}",
            prompt[:48],
        ]
        draw.multiline_text((16, 16), "\n".join(lines), fill=(235, 235, 235), font=font, spacing=6)
        buf = io.BytesIO()
        # No pnginfo/timestamps → deterministic bytes for a given request.
        img.save(buf, format="PNG")
        return buf.getvalue()
