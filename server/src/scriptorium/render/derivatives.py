"""WebP derivative generation for rendered plates (DESIGN §10 derivatives row).

Every rendered PNG (``images/plates/*.png``, ``images/cover.png``, ``images/portraits/*.png``) gets
two reader-facing WebP derivatives: a **web** image (downscaled to a per-asset max width) and a
**thumb** (320w). Both are LANCZOS resamples saved at quality 80. The full-res PNG stays archival;
the reader bundle ships only the derivatives (§4.3 ``reader_required``).

Derivation is **idempotent**: alongside each output we write a ``{out}.src.sha256`` sidecar holding
the source PNG's hash, and skip regeneration when the sidecar already matches the current source.
Re-running P7 (or a resumed bake) therefore rewrites nothing unless the source pixels changed — the
property the S10a idempotency test asserts, and what keeps repeated bakes cheap.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image

QUALITY = 80  # DESIGN §10: WebP quality 80.
THUMB_WIDTH = 320  # DESIGN §10: 320w thumbnails for every asset.


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sidecar(out: Path) -> Path:
    """The provenance sidecar for a derivative: ``0007.webp`` → ``0007.webp.src.sha256``."""
    return out.with_name(out.name + ".src.sha256")


def derive_webp(src: Path, out: Path, *, max_width: int, quality: int = QUALITY) -> bool:
    """Write ``src`` as a WebP ≤ ``max_width`` wide (LANCZOS, ``quality``). Idempotent.

    Only downscales (never upscales). Returns ``True`` if it (re)wrote ``out``, ``False`` if a
    matching ``.src.sha256`` sidecar meant the existing derivative was already current.
    """
    src_hash = _sha256_file(src)
    sidecar = _sidecar(out)
    current = sidecar.read_text(encoding="utf-8").strip() if sidecar.is_file() else None
    if out.is_file() and current == src_hash:
        return False

    with Image.open(src) as img:
        img = img.convert("RGB")
        if img.width > max_width:
            new_height = round(img.height * max_width / img.width)
            img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out, format="WEBP", quality=quality)

    sidecar.write_text(src_hash + "\n", encoding="utf-8")
    return True


def make_derivatives(src: Path, web_out: Path, thumb_out: Path, *, web_max_width: int) -> bool:
    """Produce both the web (≤ ``web_max_width``) and 320w thumb derivatives for ``src``.

    Returns ``True`` if either derivative was (re)written (i.e. the work was not fully skipped).
    """
    wrote_web = derive_webp(src, web_out, max_width=web_max_width)
    wrote_thumb = derive_webp(src, thumb_out, max_width=THUMB_WIDTH)
    return wrote_web or wrote_thumb
