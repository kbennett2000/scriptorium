"""WebP derivative generation (DESIGN §10 derivatives row) — sizing + idempotency.

Unit-level coverage of ``render/derivatives.py``: derivatives downscale to the per-asset max width
(never upscale), thumbs are 320w, and re-running is a no-op while the source is unchanged (the
``.src.sha256`` sidecar), but re-derives once the source pixels change. Bytes are never asserted.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from scriptorium.render.derivatives import _sidecar, derive_webp, make_derivatives


def _write_png(path: Path, size: tuple[int, int], color: tuple[int, int, int]) -> None:
    Image.new("RGB", size, color).save(path, format="PNG")


def _webp_width(path: Path) -> int:
    return Image.open(io.BytesIO(path.read_bytes())).size[0]


def test_make_derivatives_sizes_and_sidecars(tmp_path) -> None:
    src = tmp_path / "plate.png"
    _write_png(src, (832, 1216), (20, 30, 40))
    web, thumb = tmp_path / "web.webp", tmp_path / "thumb.webp"

    assert make_derivatives(src, web, thumb, web_max_width=1080) is True
    assert _webp_width(web) == 832  # 832 ≤ 1080 → not upscaled
    assert _webp_width(thumb) == 320
    assert _sidecar(web).is_file() and _sidecar(thumb).is_file()


def test_derive_webp_downscales_to_max_width(tmp_path) -> None:
    src = tmp_path / "portrait.png"
    _write_png(src, (1024, 1024), (10, 10, 10))
    web = tmp_path / "web.webp"
    derive_webp(src, web, max_width=768)
    assert _webp_width(web) == 768  # 1024 → 768


def test_derive_webp_is_idempotent_until_source_changes(tmp_path) -> None:
    src = tmp_path / "plate.png"
    _write_png(src, (832, 1216), (20, 30, 40))
    web = tmp_path / "web.webp"

    assert derive_webp(src, web, max_width=1080) is True  # first write
    assert derive_webp(src, web, max_width=1080) is False  # sidecar matches → skipped

    _write_png(src, (832, 1216), (200, 100, 50))  # source pixels change
    assert derive_webp(src, web, max_width=1080) is True  # re-derived
