#!/usr/bin/env python3
"""Build a complete, schema-valid, deterministic fake bundle (DESIGN §4.2).

This is R1's dev diet (a real bundle to render before any bake exists) and S10's
verify target. Everything is produced *deterministically* — fixed timestamps, fixed
flat-colour placeholder images — so re-running reproduces the committed bytes exactly
(`git diff --exit-code server/tests/fixtures/bundle/`).

What is real vs. hand-written:
- **Real P0:** a synthetic 6-page book is paginated by the actual `paginate()`; its
  `pages/*.json` and `structure.json` are genuine paginator output.
- **Hand-written but schema-valid:** meta / cast / selection / prompts and the
  placeholder images (P1–P8 don't exist yet). They are internally consistent
  (page ids, slugs, plate ids all cross-reference) and validate against the schemas.

Run from the server project so the package + deps are available:
    cd server && uv run python ../tools/make_fixture_bundle.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
# Make the server package importable even when run outside its installed env.
sys.path.insert(0, str(_REPO_ROOT / "server" / "src"))

from PIL import Image  # noqa: E402

from scriptorium.ingest.base import (  # noqa: E402
    Chapter,
    RawBook,
    normalize_source_text,
    user_book_id,
)
from scriptorium.paginate import paginate  # noqa: E402

# Fixed literal timestamp — no now(), so the bundle is byte-reproducible.
FIXED_TS = "2026-07-13T00:00:00Z"

# Native SDXL plate size and reader derivative widths (DESIGN §4.2).
NATIVE = (832, 1216)
WEB_W = 1080
THUMB_W = 320

_WORDS = (
    "lantern harbour clock tide letter ledger workshop stranger river market "
    "silver winter keeper riddle patience quiet stone plank gull salt shore bell "
    "door key song watch morning shingle net sun hair sleep water deep name flame"
).split()


def _para(seed: int, n: int) -> str:
    out = [_WORDS[(i * 7 + seed) % len(_WORDS)] for i in range(seed, seed + n)]
    return " ".join(out).capitalize() + "."


def _chapter(title: str, seed: int, nparas: int, wperpara: int) -> Chapter:
    return Chapter(title=title, paragraphs=[_para(seed + j, wperpara) for j in range(nparas)])


def _synthetic_book() -> RawBook:
    """A deterministic two-chapter book sized to paginate to exactly six pages."""
    return RawBook(
        book_id="",  # filled in below from the reconstructed source hash
        source_kind="user",
        title="The Tidewatch Fragment",
        author="A. Fixture",
        language="en",
        chapters=[
            _chapter("Chapter I", 1, 11, 150),
            _chapter("Chapter II", 100, 11, 150),
        ],
    )


# --- JSON / hashing helpers -------------------------------------------------

def _write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- placeholder images -----------------------------------------------------

def _color(name: str) -> tuple[int, int, int]:
    d = hashlib.sha256(name.encode("utf-8")).digest()
    return d[0], d[1], d[2]


def _write_image_set(bundle: Path, rel_native: str) -> None:
    """Write a native PNG plus web/thumb WebP derivatives for one image.

    ``rel_native`` is e.g. 'images/plates/0001.png' or 'images/cover.png'. The web
    and thumb variants mirror the sub-path under images/web/ and images/thumbs/.
    """
    native = Image.new("RGB", NATIVE, _color(rel_native))
    native_path = bundle / rel_native
    native_path.parent.mkdir(parents=True, exist_ok=True)
    native.save(native_path, format="PNG", optimize=True)

    sub = rel_native[len("images/") :].rsplit(".", 1)[0]  # e.g. 'plates/0001' or 'cover'
    for width, tier in ((WEB_W, "web"), (THUMB_W, "thumbs")):
        h = round(NATIVE[1] * width / NATIVE[0])
        derivative = native.resize((width, h), Image.LANCZOS)
        out = bundle / "images" / tier / f"{sub}.webp"
        out.parent.mkdir(parents=True, exist_ok=True)
        derivative.save(out, format="WEBP", quality=80, method=6)


# --- the bundle -------------------------------------------------------------

def build(out_dir: Path) -> dict:
    book = _synthetic_book()
    pb = paginate(book)
    pages = pb.pages
    assert len(pages) == 6, f"expected a 6-page fixture, paginated to {len(pages)}"

    source_text = "\n\n".join(pb.reconstruct_chapter(i) for i in range(len(book.chapters)))
    book_id = user_book_id(normalize_source_text(source_text))

    # Clean output dir (keep it byte-reproducible: no stale files linger).
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    # structure.json + pages/*.json — genuine paginator output.
    _write_json(out_dir / "structure.json", pb.structure)
    for page in pages:
        _write_json(out_dir / "pages" / f"{page['id']}.json", page)

    total_words = sum(p["word_count"] for p in pages)

    # Selected plates (hand-written, consistent with the real page ids).
    plates = [
        {"page_id": "0001", "reason": "chapter_open", "salience": 0.71,
         "status": "rendered", "added_in_revision": 1},
        {"page_id": "0003", "reason": "scene_boundary", "salience": 0.66,
         "status": "rendered", "added_in_revision": 1},
        {"page_id": "0004", "reason": "chapter_open", "salience": 0.69,
         "status": "rendered", "added_in_revision": 1},
    ]
    _write_json(out_dir / "selection.json", {
        "preset": "classic",
        "params": {"min_gap": 2, "max_gap": 6, "salience_floor": 0.55,
                   "chapter_open": True, "scene_boundary": True},
        "plates": plates,
    })

    # cast.json — one major with a portrait, one minor.
    _write_json(out_dir / "cast.json", {
        "characters": [
            {"slug": "the-clockmaker", "name": "the Clockmaker",
             "aliases": ["the old clockmaker"],
             "mention_pages": ["0001", "0002", "0003"], "major": True,
             "visual_description": "a spare, white-haired artisan in a leather apron, "
                                   "hands stained with brass polish",
             "one_line": "The keeper of the workshop at the end of the lane.",
             "tags": ["artisan", "recluse"],
             "portrait": "images/portraits/the-clockmaker.png",
             "edited_by_human": False},
            {"slug": "the-stranger", "name": "the Stranger",
             "aliases": [], "mention_pages": ["0004", "0005"], "major": False,
             "visual_description": None,
             "one_line": "A pale visitor who arrives with the winter tide.",
             "tags": ["newcomer"], "portrait": None, "edited_by_human": False},
        ],
    })

    # meta.json.
    _write_json(out_dir / "meta.json", {
        "bundle_version": 1, "book_id": book_id, "revision": 1,
        "title": book.title, "author": book.author, "language": book.language,
        "source": {"kind": "user", "retrieved_at": FIXED_TS},
        "era": "an imagined coastal town",
        "style_id": "engraving", "density_preset": "classic", "portraits_enabled": True,
        "bake": {
            "completed_at": FIXED_TS,
            "transform_service": {"url_host": "fixture.local", "transforms": {
                "cast-mentions": "0.0.0-fixture", "cast-canonicalize": "0.0.0-fixture",
                "scene-update": "0.0.0-fixture", "illustration-prompt": "0.0.0-fixture"}},
            "models": {"llm": "fixture-llm", "imagegen": "fixture-imagegen"},
            "pipeline_version": "S3-fixture",
        },
        "stats": {"pages": len(pages), "words": total_words,
                  "plates": len(plates), "chapters": len(book.chapters)},
    })

    # prompts/*.json — one per selected plate, plus cover + portrait pseudo-plates.
    prefix = ("19th-century steel engraving book illustration, fine crosshatching, "
              "monochrome ink, dramatic light, ")
    suffix = ", intricate linework, aged paper tone, high detail"
    negative = "photo, color photograph, modern, text, watermark, signature, blurry"

    def prompt_record(page_id: str, subject: str) -> dict:
        return {
            "page_id": page_id,
            "derived": {"prompt": subject, "avoid": "modern dress, machinery",
                        "scene": subject},
            "edited_prompt": None,
            "final_subject_prompt": subject,
            "wrapped_prompt": prefix + subject + suffix,
            "negative_prompt": negative + ", modern dress, machinery",
            "render": {"at": FIXED_TS,
                       "params_echo": {"seed": 1234, "width": NATIVE[0],
                                       "height": NATIVE[1], "steps": 30},
                       "attempts": 1},
        }

    prompt_subjects = {
        "0001": "a lantern-lit workshop at the end of a lane, tools on the bench",
        "0003": "the clockmaker bent over a brass mechanism by candlelight",
        "0004": "a pale stranger arriving on a grey quay as the tide turns",
        "cover": "a silvered harbour under a cold sun, a single watchful figure",
        "portrait-the-clockmaker": "bust portrait of a spare, white-haired artisan "
                                   "in a leather apron",
    }
    for page_id, subject in prompt_subjects.items():
        _write_json(out_dir / "prompts" / f"{page_id}.json", prompt_record(page_id, subject))

    # Images: plates for selected pages, cover, one portrait — each with derivatives.
    for plate in plates:
        _write_image_set(out_dir, f"images/plates/{plate['page_id']}.png")
    _write_image_set(out_dir, "images/cover.png")
    _write_image_set(out_dir, "images/portraits/the-clockmaker.png")

    # manifest.json — real hashes/sizes for every file except the manifest itself.
    reader_required = ["meta.json", "structure.json", "pages/*", "cast.json",
                       "selection.json", "images/web/**", "images/thumbs/**"]
    files = []
    for path in sorted(out_dir.rglob("*")):
        if path.is_file():
            rel = path.relative_to(out_dir).as_posix()
            files.append({"path": rel, "sha256": _sha256(path), "bytes": path.stat().st_size})

    total_reader = sum(
        f["bytes"] for f in files if _matches_any(f["path"], reader_required)
    )
    _write_json(out_dir / "manifest.json", {
        "book_id": book_id, "revision": 1, "bundle_version": 1,
        "files": files, "reader_required": reader_required,
        "total_bytes_reader": total_reader,
    })

    return {"book_id": book_id, "pages": len(pages), "words": total_words,
            "files": len(files), "out": str(out_dir)}


def _matches_any(rel_path: str, patterns: list[str]) -> bool:
    for pat in patterns:
        if pat.endswith("/**"):
            if rel_path.startswith(pat[:-2]):  # keep trailing '/'
                return True
        elif pat.endswith("/*"):
            prefix = pat[:-1]  # keep trailing '/'
            if rel_path.startswith(prefix) and "/" not in rel_path[len(prefix):]:
                return True
        elif rel_path == pat:
            return True
    return False


def main() -> None:
    default_out = _REPO_ROOT / "server" / "tests" / "fixtures" / "bundle"
    ap = argparse.ArgumentParser(description="Build the deterministic fixture bundle.")
    ap.add_argument("--out", type=Path, default=default_out,
                    help=f"output bundle directory (default: {default_out})")
    args = ap.parse_args()
    info = build(args.out)
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
