"""Imagegen client protocol + a deterministic fake (DESIGN §10).

The bake's render phase (P7) talks to an image-generation service only through the
:class:`ImagegenClient` protocol. :class:`FakeImagegen` is the offline stand-in used by every
test and by the S9 demo render stub: it produces a **deterministic** placeholder PNG with the
prompt's hash burned into the pixels — no GPU, no network. Same ``(prompt, size, seed)`` in →
byte-identical PNG out, which is what lets tests assert determinism without asserting image
content (CLAUDE.md: never assert exact image content).

**S10 owns the real client.** S10 reads imagegen-service's actual API and implements a real
:class:`ImagegenClient` against it (ADR-0011), keeping ``FakeImagegen`` as the test double. This
module deliberately ships *only* the protocol + fake in S9 — no HTTP, no unload, no derivatives.
"""

from __future__ import annotations

import hashlib
import io
from typing import Protocol, runtime_checkable

from PIL import Image, ImageDraw, ImageFont

# DESIGN §10 render sizes (plate/cover); portraits are 1024×1024. The stub renders every plate at
# the plate size — the real P7 (S10) sizes per asset. Kept here so the fake has a sensible default.
PLATE_SIZE: tuple[int, int] = (832, 1216)


@runtime_checkable
class ImagegenClient(Protocol):
    """The image-generation surface P7 depends on (DESIGN §10).

    ``txt2img`` returns PNG bytes; ``health`` reports reachability (used by the GPU gate in the
    real S10 phase). Style rides entirely in ``prompt``/``negative`` — the client is style-neutral.
    """

    async def txt2img(
        self,
        prompt: str,
        negative: str = "",
        width: int = PLATE_SIZE[0],
        height: int = PLATE_SIZE[1],
        seed: int | None = None,
    ) -> bytes:
        """Render ``prompt`` to PNG bytes at ``width``×``height``."""
        ...

    async def health(self) -> bool:
        """True iff the service is reachable."""
        ...


def _digest(prompt: str, width: int, height: int, seed: int | None) -> str:
    """A stable hex digest of the full render request (drives both color and burned-in text)."""
    payload = f"{prompt}\x00{width}x{height}\x00{seed}".encode()
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
    ) -> bytes:
        return self.render(prompt, width=width, height=height, seed=seed)

    async def health(self) -> bool:
        return True

    def render(
        self,
        prompt: str,
        *,
        width: int = PLATE_SIZE[0],
        height: int = PLATE_SIZE[1],
        seed: int | None = None,
    ) -> bytes:
        """Synchronous core: deterministic placeholder PNG bytes for ``prompt``."""
        digest = _digest(prompt, width, height, seed)
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
