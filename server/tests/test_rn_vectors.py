"""The Python half of the shared `-rN` resolution contract (DESIGN §4.4).

Both the server (`scriptorium.library.checkout.resolve_reader_files`) and the TypeScript reader
(`reader/src/shelf/resolve.ts`) resolve a manifest's reader-required files to one current image per
plate. The two impls are pinned against ONE vector file — `shared/test-vectors/rn-resolution.json` —
so a drift in either surfaces as a red suite here or in `reader/src/shelf/resolve.test.ts`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scriptorium.library.checkout import resolve_reader_files, resolved_total_bytes

_VECTORS = (
    Path(__file__).resolve().parents[2] / "shared" / "test-vectors" / "rn-resolution.json"
)


def _cases() -> list[dict]:
    return json.loads(_VECTORS.read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", _cases(), ids=lambda c: c["name"])
def test_shared_rn_vector(case: dict) -> None:
    manifest = case["manifest"]
    resolved = [e["path"] for e in resolve_reader_files(manifest)]
    assert resolved == case["expected"]
    if "expected_total_bytes" in case:
        assert resolved_total_bytes(manifest) == case["expected_total_bytes"]
