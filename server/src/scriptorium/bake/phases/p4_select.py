"""P4 — deterministic plate selection (DESIGN §8).

The pipeline's **first rest→rest CPU phase**: it advances a job ``ledger_done → selected`` with
no GPU work, so — unlike P1/P2/P3 — it needs no ``*_running`` state and no enter/run split (enter
phases exist only so a GPU phase can park on ``waiting_gpu``; a CPU phase skips the gate). One
unit reads the merged page ledgers, runs the pure :func:`~scriptorium.selection.engine.select`
engine, and writes a schema-valid ``selection.json``.

**Scores come from ``pages/*.json``, not ``ledgers/*.json``.** P3 merged the effective (gap-filled)
ledger onto each page; P4 consumes only the two spoiler-safe numbers from it — ``scene_changed``
and ``visual_salience`` — never any text field (the spoiler invariant, enforced structurally by
:class:`~scriptorium.selection.engine.PageScore`).

**Fresh selection only (revision 1).** This phase always produces a first-pass selection. Turning
the density knob later re-runs the engine and merges via
:func:`scriptorium.selection.reselect.reselect`; wiring that into a revision re-bake happens where
revisions are bumped (re-bake / publish), outside this phase's ``ledger_done → selected`` hop.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ... import schemas
from ...selection.engine import PRESETS, PageScore, PlateChoice, select
from ...selection.segment import expand_choices
from ..job import Job, JobState
from .base import Unit

_DEFAULT_PRESET = "classic"


def _book_dir(cfg: Any, job: Job) -> Path:
    return cfg.work_dir / job.book_id


def _pages_dir(cfg: Any, job: Job) -> Path:
    return _book_dir(cfg, job) / "pages"


def _selection_path(cfg: Any, job: Job) -> Path:
    return _book_dir(cfg, job) / "selection.json"


def _structure_path(cfg: Any, job: Job) -> Path:
    return _book_dir(cfg, job) / "structure.json"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _page_scores(cfg: Any, job: Job) -> list[PageScore]:
    """Build the spoiler-safe score list from each merged page ledger (numbers/booleans only)."""
    scores: list[PageScore] = []
    for page_file in sorted(_pages_dir(cfg, job).glob("*.json")):
        page = _read_json(page_file)
        ledger = page.get("ledger") or {}
        scores.append(
            PageScore(
                seq=page["seq"],
                page_id=page["id"],
                chapter=page["chapter"],
                scene_changed=bool(ledger.get("scene_changed", False)),
                visual_salience=float(ledger.get("visual_salience", 0.0)),
            )
        )
    return scores


def _page_texts(cfg: Any, job: Job) -> dict[str, str]:
    """Map page_id -> canonical page text.

    Used only to segment *already-selected* pages (in P4, not the engine), so no page's text is ever
    an input to the selection decision — the spoiler invariant holds.
    """
    texts: dict[str, str] = {}
    for page_file in sorted(_pages_dir(cfg, job).glob("*.json")):
        page = _read_json(page_file)
        texts[page["id"]] = page.get("text", "")
    return texts


def _images_per_scene(job: Job) -> int:
    """Pictures-per-scene from bake config (≥1; defaults to 1 for pre-feature configs)."""
    try:
        return max(1, int(job.bake_config.get("images_per_scene", 1)))
    except (TypeError, ValueError):
        return 1


def _plate_doc(pc: PlateChoice) -> dict:
    """Serialize a fresh (revision-1, selected) plate choice. Compound fields are emitted only for
    the evenly-spaced extras, so a page's base plate stays byte-identical to a single-image bake."""
    doc: dict[str, Any] = {"page_id": pc.page_id}
    if pc.plate_id is not None:
        doc["plate_id"] = pc.plate_id
    if pc.anchor is not None:
        doc["anchor"] = pc.anchor
    if pc.segment_index is not None:
        doc["segment_index"] = pc.segment_index
    doc.update({
        "reason": pc.reason,
        "salience": pc.salience,
        "status": "selected",
        "added_in_revision": 1,
    })
    return doc


class P4Select:
    """P4: select plates from the merged page ledgers (CPU, one unit)."""

    name = "p4_select"
    from_state = JobState.LEDGER_DONE
    to_state = JobState.SELECTED
    is_gpu = False

    def units(self, job: Job, cfg: Any) -> list[Unit]:
        return [Unit(id="select")]

    def unit_done(self, job: Job, cfg: Any, unit: Unit) -> bool:
        path = _selection_path(cfg, job)
        if not path.is_file():
            return False
        try:
            _read_json(path)
            return True
        except json.JSONDecodeError:
            return False

    def run_unit(self, job: Job, cfg: Any, unit: Unit) -> None:
        preset = job.bake_config.get("density_preset", _DEFAULT_PRESET)
        if preset not in PRESETS:
            preset = _DEFAULT_PRESET
        params = PRESETS[preset]

        structure_path = _structure_path(cfg, job)
        structure = _read_json(structure_path) if structure_path.is_file() else {"chapters": []}

        chosen = select(_page_scores(cfg, job), structure, params)

        # Expand each selected page into up to `images_per_scene` evenly-spaced illustrations. The
        # engine chose *which* pages (text-free); segmentation needs the page text, so it happens
        # here in P4. A scene yields at most one plate per paragraph.
        expanded = expand_choices(chosen, _page_texts(cfg, job), _images_per_scene(job))

        doc = {
            "preset": preset,
            "params": params.as_dict(),
            "plates": [_plate_doc(pc) for pc in expanded],
        }
        schemas.validate("selection", doc)
        _write_json(_selection_path(cfg, job), doc)
