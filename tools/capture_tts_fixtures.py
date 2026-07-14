#!/usr/bin/env python3
"""Capture real TTS fixtures for the cast pipeline (BUILD-PLAN §0 fixture rule).

Run this **once on the LAN**, with the text-transform-service (TTS T5) up on the 5070, to
replace the hand-written fixtures under ``server/tests/fixtures/tts/`` with genuine captures:

    cd server && TTS_URL=http://<5070-host>:8712 uv run python ../tools/capture_tts_fixtures.py

It repaginates ``server/tests/fixtures/sources/pg35.txt`` (The Time Machine) with the real
paginator, calls ``cast-mentions`` for the first 6 pages, runs the deterministic reducer to
pick the two biggest major characters, calls ``cast-canonicalize`` for those two, then threads
``scene-update`` over the same 6 pages (feeding each output as the next ``prior_ledger``), and
writes the full response envelopes as fixtures. Tests assert schema/shape only, so a re-capture
that changes wording stays green (CLAUDE.md: never assert exact LLM content).

This tool is **not** exercised by the offline test suite — it needs a live GPU service.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "server" / "src"))

import httpx  # noqa: E402

from scriptorium.bake.reduce_cast import reduce_cast  # noqa: E402
from scriptorium.ingest.base import KIND_TEXT, SourceSpec, load  # noqa: E402
from scriptorium.paginate.engine import paginate  # noqa: E402

_PAGES_TO_CAPTURE = 6
_CHARACTERS_TO_CAPTURE = 2
_SOURCE = _REPO_ROOT / "server" / "tests" / "fixtures" / "sources" / "pg35.txt"
_OUT = _REPO_ROOT / "server" / "tests" / "fixtures" / "tts"


async def _post_transform(
    base: str, name: str, text: str, options: dict | None = None
) -> dict:
    url = f"{base.rstrip('/')}/v1/transform/{name}"
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(url, json={"text": text, "options": options or {}})
    resp.raise_for_status()
    return resp.json()  # full {output, meta} envelope


def _write(path: Path, envelope: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(f"wrote {path.relative_to(_REPO_ROOT)}")


async def main() -> int:
    base = os.environ.get("TTS_URL")
    if not base:
        print("TTS_URL is not set — cannot capture. See fixtures README.", file=sys.stderr)
        return 2

    book = paginate(load(SourceSpec(kind=KIND_TEXT, path=_SOURCE, filename="pg35.txt")))
    pages = book.pages[:_PAGES_TO_CAPTURE]

    reduce_input: list[dict] = []
    for page in pages:
        env = await _post_transform(base, "cast-mentions", page["text"])
        _write(_OUT / "cast-mentions" / f"{page['id']}.json", env)
        reduce_input.append({"page_id": page["id"], "mentions": env["output"]["mentions"]})

    groups = reduce_cast(reduce_input)
    majors = [g for g in groups if g["major"]][:_CHARACTERS_TO_CAPTURE]
    for g in majors:
        options = {"name": g["name"], "aliases": g["aliases"], "descriptors": g["descriptors"]}
        env = await _post_transform(base, "cast-canonicalize", "", options)
        _write(_OUT / "cast-canonicalize" / f"{g['slug']}.json", env)

    # P3: thread scene-update over the pages in order — each output is the next prior_ledger.
    cast_names = [g["name"] for g in groups][:40]
    prior_ledger: dict | None = None
    for page in pages:
        options = {"prior_ledger": prior_ledger, "cast_names": cast_names}
        env = await _post_transform(base, "scene-update", page["text"], options)
        _write(_OUT / "scene-update" / f"{page['id']}.json", env)
        prior_ledger = env["output"]

    print(
        f"captured {len(pages)} mention pages + {len(majors)} canonicalizations "
        f"+ {len(pages)} scene ledgers"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
