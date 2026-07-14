"""FakeImagegen — deterministic placeholder PNGs (DESIGN §10).

Asserts the fake's *contract* only (valid PNG, requested size, reproducibility) — never pixel
content, per CLAUDE.md. Determinism is what lets the render-stub tests compare bytes.
"""

from __future__ import annotations

import asyncio
import io

from PIL import Image

from scriptorium.render.imagegen import PLATE_SIZE, FakeImagegen


def _png(prompt: str, **kw) -> bytes:
    return asyncio.run(FakeImagegen().txt2img(prompt, **kw))


def test_txt2img_returns_valid_png_of_requested_size() -> None:
    data = _png("a solitary figure on a stone quay", width=640, height=480)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    img = Image.open(io.BytesIO(data))
    img.verify()
    assert Image.open(io.BytesIO(data)).size == (640, 480)


def test_default_size_is_the_plate_size() -> None:
    assert Image.open(io.BytesIO(_png("x"))).size == PLATE_SIZE


def test_same_request_is_byte_identical() -> None:
    assert _png("the same prompt") == _png("the same prompt")


def test_distinct_prompts_and_seeds_differ() -> None:
    base = _png("prompt A")
    assert base != _png("prompt B")
    assert base != _png("prompt A", seed=7)
    assert base != _png("prompt A", width=800)


def test_health_is_true() -> None:
    assert asyncio.run(FakeImagegen().health()) is True
