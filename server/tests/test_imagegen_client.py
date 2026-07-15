"""imagegen client style passthrough (ADR-0013).

`RealImagegenClient` optionally forwards a `style` preset name to imagegen-service `/generate`
so the service applies that style's LoRA. When `style` is None the request body is byte-identical
to the pre-ADR-0013 client (prompt-only). Never asserts image content (CLAUDE.md) — request shape
and the fake's determinism contract only.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import respx

from scriptorium.render.imagegen import FakeImagegen, RealImagegenClient

_BASE = "http://imagegen.test:8189"
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16  # any bytes; the client just returns resp.content


def _client() -> RealImagegenClient:
    # RealImagegenClient only reads cfg.imagegen_url.
    return RealImagegenClient(SimpleNamespace(imagegen_url=_BASE))  # type: ignore[arg-type]


@respx.mock
def test_style_omitted_from_body_when_none() -> None:
    route = respx.post(f"{_BASE}/generate").mock(return_value=httpx.Response(200, content=_PNG))
    asyncio.run(_client().txt2img("a quiet room", "blurry", 832, 1216, 5))
    body = respx.calls.last.request.read()
    import json

    sent = json.loads(body)
    assert "style" not in sent
    assert sent == {"prompt": "a quiet room", "negativePrompt": "blurry",
                    "width": 832, "height": 1216, "seed": 5}
    assert route.called


@respx.mock
def test_style_forwarded_when_set() -> None:
    respx.post(f"{_BASE}/generate").mock(return_value=httpx.Response(200, content=_PNG))
    asyncio.run(_client().txt2img("a quiet room", "", 832, 1216, 5, style="oil painting"))
    import json

    sent = json.loads(respx.calls.last.request.read())
    assert sent["style"] == "oil painting"


def test_fake_style_none_matches_no_style_arg() -> None:
    # Byte-stability: passing style=None must not change the placeholder vs. omitting it entirely.
    a = asyncio.run(FakeImagegen().txt2img("p", seed=1))
    b = asyncio.run(FakeImagegen().txt2img("p", seed=1, style=None))
    assert a == b


def test_fake_distinct_styles_differ() -> None:
    base = asyncio.run(FakeImagegen().txt2img("p", seed=1))
    oil = asyncio.run(FakeImagegen().txt2img("p", seed=1, style="oil painting"))
    anime = asyncio.run(FakeImagegen().txt2img("p", seed=1, style="anime"))
    assert base != oil
    assert oil != anime
