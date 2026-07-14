"""P1 — per-page character-mention extraction (DESIGN §7.1, transform ``cast-mentions``).

Two phases live here:

- :class:`MentionsEnter` — the CPU "claim" step ``ingested → mentions_running``. It has no
  units (P0 already produced the pages) and exists only so the GPU phase that follows can
  sit on a ``*_running`` state — the runner may only park on ``waiting_gpu`` from a GPU state
  (``GPU_STATES``), so a GPU phase's ``from_state`` must be one. This mirrors how
  :class:`~scriptorium.bake.phases.p2_cast.CastReduce` feeds ``cast_running``.
- :class:`CastMentions` — the GPU phase ``mentions_running → mentions_done``. One unit per
  page; each writes ``mentions/{page_id}.json`` (the raw ``cast-mentions`` output).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..job import Job, JobState
from ..tts_client import TtsClient
from .base import Unit


def _pages_dir(cfg: Any, job: Job) -> Path:
    return cfg.work_dir / job.book_id / "pages"


def mentions_dir(cfg: Any, job: Job) -> Path:
    return cfg.work_dir / job.book_id / "mentions"


class MentionsEnter:
    """Zero-unit CPU transition ``ingested → mentions_running`` (see module docstring)."""

    name = "mentions_enter"
    from_state = JobState.INGESTED
    to_state = JobState.MENTIONS_RUNNING
    is_gpu = False

    def units(self, job: Job, cfg: Any) -> list[Unit]:
        return []

    def unit_done(self, job: Job, cfg: Any, unit: Unit) -> bool:  # pragma: no cover
        return True  # no units, so never consulted

    def run_unit(self, job: Job, cfg: Any, unit: Unit) -> None:  # pragma: no cover
        return None


class CastMentions:
    """P1: extract character mentions for every page (GPU-LLM, unit = page)."""

    name = "p1_mentions"
    from_state = JobState.MENTIONS_RUNNING
    to_state = JobState.MENTIONS_DONE
    is_gpu = True

    def units(self, job: Job, cfg: Any) -> list[Unit]:
        pages = _pages_dir(cfg, job)
        if not pages.is_dir():
            return []
        return [Unit(id=p.stem) for p in sorted(pages.glob("*.json"))]

    def unit_done(self, job: Job, cfg: Any, unit: Unit) -> bool:
        path = mentions_dir(cfg, job) / f"{unit.id}.json"
        if not path.is_file():
            return False
        try:
            json.loads(path.read_text(encoding="utf-8"))
            return True
        except json.JSONDecodeError:
            return False

    async def run_unit(self, job: Job, cfg: Any, unit: Unit) -> None:
        page_path = _pages_dir(cfg, job) / f"{unit.id}.json"
        page = json.loads(page_path.read_text(encoding="utf-8"))
        output = await TtsClient(cfg).transform("cast-mentions", page["text"])

        out_dir = mentions_dir(cfg, job)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{unit.id}.json").write_text(
            json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
