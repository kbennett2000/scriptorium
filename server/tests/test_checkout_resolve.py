"""Unit tests for the `-rN` checkout resolution (DESIGN §4.4, NOTES From S10b).

`resolve_reader_files` must expand the reader_required globs and collapse every image variant group
to its highest `-rN` (base = revision 1), leaving JSON files untouched. Pure function — no server.
"""

from __future__ import annotations

from scriptorium.library.checkout import (
    matches_any,
    resolve_reader_files,
    resolved_total_bytes,
)

_READER_REQUIRED = [
    "meta.json", "structure.json", "pages/*", "cast.json", "selection.json",
    "images/web/**", "images/thumbs/**",
]


def _mf(paths_bytes: dict[str, int]) -> dict:
    return {
        "reader_required": _READER_REQUIRED,
        "files": [{"path": p, "sha256": f"h{i}", "bytes": b}
                  for i, (p, b) in enumerate(paths_bytes.items())],
    }


def test_matches_any_dialect() -> None:
    assert matches_any("pages/0001.json", ["pages/*"])
    assert not matches_any("pages/sub/x.json", ["pages/*"])  # /* is single-segment
    assert matches_any("images/web/plates/0001.webp", ["images/web/**"])
    assert matches_any("meta.json", ["meta.json"])
    assert not matches_any("images/plates/0001.png", ["images/web/**", "images/thumbs/**"])


def test_base_only_passes_through() -> None:
    mf = _mf({"meta.json": 10, "images/web/plates/0001.webp": 100})
    got = {e["path"] for e in resolve_reader_files(mf)}
    assert got == {"meta.json", "images/web/plates/0001.webp"}


def test_highest_variant_wins() -> None:
    mf = _mf({
        "images/web/plates/0001.webp": 100,
        "images/web/plates/0001-r2.webp": 110,
        "images/web/plates/0001-r3.webp": 120,
    })
    got = {e["path"] for e in resolve_reader_files(mf)}
    assert got == {"images/web/plates/0001-r3.webp"}
    assert resolved_total_bytes(mf) == 120


def test_full_res_png_never_reader_required() -> None:
    # images/plates/*.png (archival) is not under images/web|thumbs — excluded entirely.
    mf = _mf({"images/plates/0001.png": 999, "images/web/plates/0001.webp": 50})
    got = {e["path"] for e in resolve_reader_files(mf)}
    assert got == {"images/web/plates/0001.webp"}


def test_json_and_cover_portrait_variants() -> None:
    mf = _mf({
        "pages/0001.json": 5, "pages/0002.json": 6,
        "images/thumbs/cover.webp": 20, "images/thumbs/cover-r2.webp": 22,
        "images/web/portraits/wanderer.webp": 30,
        "images/web/portraits/wanderer-r2.webp": 33,
    })
    got = {e["path"] for e in resolve_reader_files(mf)}
    assert got == {
        "pages/0001.json", "pages/0002.json",
        "images/thumbs/cover-r2.webp",
        "images/web/portraits/wanderer-r2.webp",
    }


def test_web_and_thumb_variants_resolve_independently() -> None:
    # A regen writes both a web and a thumb -r2; each group collapses on its own.
    mf = _mf({
        "images/web/plates/0006.webp": 100, "images/web/plates/0006-r2.webp": 105,
        "images/thumbs/plates/0006.webp": 40, "images/thumbs/plates/0006-r2.webp": 42,
    })
    got = {e["path"] for e in resolve_reader_files(mf)}
    assert got == {"images/web/plates/0006-r2.webp", "images/thumbs/plates/0006-r2.webp"}
