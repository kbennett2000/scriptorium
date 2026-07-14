#!/usr/bin/env python3
"""Seed a book at ``prompts_draft`` from the committed fixture bundle — a **dev-only** helper.

Reaching the admin review gate normally requires the full P1–P5 pipeline, which calls the TTS GPU
service. This box has no TTS, so this script materializes a book directly at ``prompts_draft`` in
the server work dir so the S9b admin UI's **no-GPU acceptance walk** (review → edit prompt → toggle
plate → approve → FakeImagegen stub render) can be performed end-to-end without any GPU service.

It copies ``server/tests/fixtures/bundle/`` (pages, structure, selection, cast, prompts) into
``work/{book_id}/`` — rewriting every selection plate's status to ``selected`` so Approve has real
work to lock, and deliberately NOT copying ``images/`` so the P7 stub renders fresh placeholders and
sets ``job.render_stub``. It then writes a started job record at ``prompts_draft``.

Not wired into the pipeline; safe to re-run (it overwrites the seeded book). Run from the server
project so the package + deps are importable:

    cd server && uv run python ../tools/seed_review_book.py [--book-id ID]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
# Make the server package importable even when run outside its installed env.
sys.path.insert(0, str(_REPO_ROOT / "server" / "src"))

from scriptorium.bake.job import Job, JobState  # noqa: E402
from scriptorium.config import load_config  # noqa: E402

_BUNDLE = _REPO_ROOT / "server" / "tests" / "fixtures" / "bundle"
_DEFAULT_BOOK_ID = "usr-seedreview01"


def _copy_selected(src: Path, dst: Path) -> int:
    """Copy selection.json, flipping every plate to ``selected``. Returns the plate count."""
    doc = json.loads(src.read_text(encoding="utf-8"))
    for plate in doc.get("plates", []):
        plate["status"] = "selected"
    dst.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(doc.get("plates", []))


def seed(book_id: str) -> Path:
    cfg = load_config()
    work = cfg.work_dir / book_id
    if work.exists():
        shutil.rmtree(work)
    (work / "pages").mkdir(parents=True, exist_ok=True)

    # pages/ + structure.json + cast.json — copied verbatim.
    for page in sorted((_BUNDLE / "pages").glob("*.json")):
        shutil.copy2(page, work / "pages" / page.name)
    shutil.copy2(_BUNDLE / "structure.json", work / "structure.json")
    shutil.copy2(_BUNDLE / "cast.json", work / "cast.json")

    # prompts/ — copied verbatim (page plates + cover/portrait pseudo-plates).
    (work / "prompts").mkdir(exist_ok=True)
    for prompt in sorted((_BUNDLE / "prompts").glob("*.json")):
        shutil.copy2(prompt, work / "prompts" / prompt.name)

    # selection.json — statuses reset to `selected` so Approve → P7 stub has work to do.
    plate_count = _copy_selected(_BUNDLE / "selection.json", work / "selection.json")

    job = Job(
        id=book_id,
        book_id=book_id,
        state=JobState.PROMPTS_DRAFT,
        title="Seed Review Demo",
        started=True,
    )
    job.save(cfg)

    print(f"Seeded {book_id} at prompts_draft ({plate_count} plates) in {work}")
    print("Open the admin UI, find the book, and run Review → edit → approve → stub render.")
    return work


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book-id", default=_DEFAULT_BOOK_ID, help="book id to seed")
    args = parser.parse_args()
    seed(args.book_id)


if __name__ == "__main__":
    main()
