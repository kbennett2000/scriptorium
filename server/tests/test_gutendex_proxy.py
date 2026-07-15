"""Gutendex search proxy (DESIGN §11.1) — respx-mocked; never 500.

The wizard searches Gutendex through the server (readers never touch the network). The proxy trims
the upstream payload to what the picker needs and degrades to 502 on any upstream failure.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from scriptorium.app import app

_GUTENDEX = "https://gutendex.com/books/"

_UPSTREAM = {
    "count": 1,
    "results": [
        {
            "id": 35,
            "title": "The Time Machine",
            "authors": [{"name": "Wells, H. G. (Herbert George)", "birth_year": 1866}],
            "formats": {
                "text/html": "https://example.org/35.html",
                "text/plain; charset=utf-8": "https://example.org/35.txt",
            },
        }
    ],
}


@pytest.fixture
def client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setenv("SCRIPTORIUM_DATA", str(tmp_path))
    return TestClient(app)


def test_empty_query_returns_no_results_without_calling_upstream(client) -> None:
    assert client.get("/api/admin/gutendex").json() == {"results": []}


@respx.mock
def test_proxy_trims_upstream(client) -> None:
    respx.get(_GUTENDEX).mock(return_value=httpx.Response(200, json=_UPSTREAM))
    r = client.get("/api/admin/gutendex", params={"q": "time machine"})
    assert r.status_code == 200, r.text
    results = r.json()["results"]
    assert results == [{
        "id": 35,
        "title": "The Time Machine",
        "authors": ["Wells, H. G. (Herbert George)"],
        "download_url": "https://example.org/35.txt",
    }]


@respx.mock
def test_upstream_failure_degrades_to_502_not_500(client) -> None:
    respx.get(_GUTENDEX).mock(side_effect=httpx.ConnectError("boom"))
    r = client.get("/api/admin/gutendex", params={"q": "x"})
    assert r.status_code == 502


@respx.mock
def test_proxy_follows_redirects(client) -> None:
    """Regression: gutendex.com 301-redirects; the proxy must follow, not surface a 502.

    Historically the proxy hit /books (no slash) and gutendex 301'd to /books/ with the
    redirect unfollowed, so the wizard's search failed. Guard that any such redirect is
    followed through to the real payload.
    """
    redirected = "https://gutendex.com/v2/books/"
    respx.get(_GUTENDEX).mock(
        return_value=httpx.Response(301, headers={"Location": redirected})
    )
    respx.get(redirected).mock(return_value=httpx.Response(200, json=_UPSTREAM))
    r = client.get("/api/admin/gutendex", params={"q": "time machine"})
    assert r.status_code == 200, r.text
    assert r.json()["results"][0]["id"] == 35
