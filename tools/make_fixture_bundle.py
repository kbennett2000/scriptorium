#!/usr/bin/env python3
"""Regenerate the committed fixture bundle via the *real* P0→P8 pipeline (DESIGN §4.2).

This is R1's dev diet (a real published bundle to build the reader against) and S10b's
``verify_bundle`` target. Unlike the S3 hand-written version, it now drives the genuine bake —
real P0 (ingest + paginate), the registered phases through the real runner (TTS mocked via respx),
:class:`FakeImagegen` for pixels, and the real **P8 publish** — so every artifact (including the
``prompts/*`` that S8 flagged as stale) is exactly what production emits. The build is deterministic
(fixed source, fixed mocks, deterministic FakeImagegen pixels, frozen clock + pinned ``meta.bake``),
so re-running reproduces the committed bytes exactly (``git diff --exit-code
server/tests/fixtures/bundle/``).

Run from the server project so the package + dev deps (respx) are available:
    cd server && uv run python ../tools/make_fixture_bundle.py
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
# Make the server package + the shared test harness importable outside the installed env.
sys.path.insert(0, str(_REPO_ROOT / "server" / "src"))
sys.path.insert(0, str(_REPO_ROOT / "server" / "tests"))

from _pipeline_build import build_fixture_bundle  # noqa: E402


def main() -> None:
    default_out = _REPO_ROOT / "server" / "tests" / "fixtures" / "bundle"
    ap = argparse.ArgumentParser(description="Regenerate the fixture bundle via the real pipeline.")
    ap.add_argument("--out", type=Path, default=default_out,
                    help=f"output bundle directory (default: {default_out})")
    args = ap.parse_args()
    with tempfile.TemporaryDirectory(prefix="scriptorium-fixture-") as tmp:
        info = build_fixture_bundle(args.out, Path(tmp))
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
