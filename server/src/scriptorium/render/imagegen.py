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

import base64
import hashlib
import io
from typing import Any, Protocol, runtime_checkable

import httpx
from PIL import Image, ImageDraw, ImageFont

from ..bake.phases.base import GpuUnavailable, PipelineBug, UnitFailed
from ..config import Config

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
        """
        ...

    async def health(self) -> bool:
        """True iff the service is reachable."""
        ...


# imagegen-service is a ComfyUI proxy: /generate can load an SDXL model on the first call, so the
# generate timeout is generous (the service's own tier budget tops out at 300s); health is quick.
_GENERATE_TIMEOUT_S = 300.0
_HEALTH_TIMEOUT_S = 15.0


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
        )

    async def health(self) -> bool:
        return True

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
    ) -> bytes:
        """Synchronous core: deterministic placeholder PNG bytes for ``prompt``."""
        digest = _digest(
            prompt, width, height, seed, style, checkpoint,
            references, reference_strength, reference_start,
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
