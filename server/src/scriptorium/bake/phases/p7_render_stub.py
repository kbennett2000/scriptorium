"""P7 render **stub** — a demo phase, replaced wholesale by S10's real render (DESIGN §10, §11.3).

S9's review gate makes invariant #4 ("no plate rendered before approval") real, and to *show* the
post-approval flow end-to-end without a GPU this stub renders a :class:`FakeImagegen` placeholder
per approved plate. It exists purely so wizard→review→approve→render is demonstrable now;
**S10 deletes this file** and lands the real ``p7_render.py``.

The seam this stub deliberately does NOT cross (all S10):

- **Not a GPU phase.** ``is_gpu=False``: FakeImagegen needs no GPU, so no gate/WoL/``waiting_gpu``.
  The real P7 is ``is_gpu=True`` with an enter-split (``approved → rendering`` CPU claim, then a
  GPU ``rendering → …`` phase) and a mandatory pre-phase **TTS unload** (ADR-0009).
- **No style wrap / negative prompt.** It renders ``final_subject_prompt`` as-is; the real P7
  assembles ``wrapped_prompt``/``negative_prompt`` per §10 and records them on ``prompts/*.json``.
- **No derivatives, no manifest, no publish.** No WebP/thumb pipeline, no ``render`` provenance
  block, no ``images/web`` or ``images/thumbs``. The job **rests at ``rendering``** — publish is
  S10 (``rendering → published``); nothing advances a job out of ``rendering`` in S9.

Units are every drafted plate (``prompts/*.json`` — page plates plus the ``cover`` / ``portrait-*``
pseudo-plates); each writes ``images/plates/{page_id}.png``. Page-plate ``selection.json`` entries
flip ``approved → rendered``; the pseudo-plates have no selection entry (they live only in
``prompts/``). The job's ``render_stub`` flag is set so S10 / the UI know these are placeholders.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ...render.imagegen import FakeImagegen
from ..job import Job, JobState
from .base import Unit


def _book_dir(cfg: Any, job: Job) -> Path:
    return cfg.work_dir / job.book_id


def _prompts_dir(cfg: Any, job: Job) -> Path:
    return _book_dir(cfg, job) / "prompts"


def _plates_dir(cfg: Any, job: Job) -> Path:
    return _book_dir(cfg, job) / "images" / "plates"


def _selection_path(cfg: Any, job: Job) -> Path:
    return _book_dir(cfg, job) / "selection.json"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _plate_ids(cfg: Any, job: Job) -> list[str]:
    """Every drafted plate id (page plates + cover/portrait pseudo-plates), in a stable order."""
    prompts = _prompts_dir(cfg, job)
    if not prompts.is_dir():
        return []
    return [p.stem for p in sorted(prompts.glob("*.json"))]


class RenderStub:
    """Demo P7: render a FakeImagegen placeholder per approved plate (``approved → rendering``)."""

    name = "p7_render_stub"
    from_state = JobState.APPROVED
    to_state = JobState.RENDERING
    is_gpu = False  # FakeImagegen is pure-CPU; the real S10 P7 is is_gpu=True (see docstring)

    def units(self, job: Job, cfg: Any) -> list[Unit]:
        return [Unit(id=pid) for pid in _plate_ids(cfg, job)]

    def unit_done(self, job: Job, cfg: Any, unit: Unit) -> bool:
        return (_plates_dir(cfg, job) / f"{unit.id}.png").is_file()

    async def run_unit(self, job: Job, cfg: Any, unit: Unit) -> None:
        prompt_doc = _read_json(_prompts_dir(cfg, job) / f"{unit.id}.json")
        png = await FakeImagegen().txt2img(prompt_doc["final_subject_prompt"])

        out = _plates_dir(cfg, job) / f"{unit.id}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(png)

        # Page plates carry a selection entry; flip it to rendered. Pseudo-plates (cover/portrait)
        # live only in prompts/, so there is nothing to update for them.
        if unit.id.isdigit():
            self._mark_rendered(cfg, job, unit.id)
        job.render_stub = True

    def _mark_rendered(self, cfg: Any, job: Job, page_id: str) -> None:
        path = _selection_path(cfg, job)
        if not path.is_file():
            return
        doc = _read_json(path)
        for plate in doc.get("plates", []):
            if plate["page_id"] == page_id and plate["status"] != "retired":
                plate["status"] = "rendered"
        _write_json(path, doc)
