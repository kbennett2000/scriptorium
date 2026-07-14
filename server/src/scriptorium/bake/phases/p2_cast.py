"""P2 — cast reduce + canonicalize (DESIGN §7.1/§7.2), producing ``cast.json``.

Two phases, mirroring P1's enter/run split so the GPU half sits on a ``*_running`` state:

- :class:`CastReduce` — CPU step ``mentions_done → cast_running``. Reads every
  ``mentions/{page}.json``, runs the pure :func:`~scriptorium.bake.reduce_cast.reduce_cast`,
  writes the intermediate ``cast/groups.json`` (with reducer-only fields ``is_person`` /
  ``descriptors``) and an initial schema-valid ``cast.json`` (every ``visual_description``
  still ``null``). One ``reduce`` unit.
- :class:`CastCanonicalize` — GPU step ``cast_running → cast_done``. One unit per **major**;
  each calls ``cast-canonicalize`` and writes ``cast/canon/{slug}.json``, then re-assembles
  ``cast.json`` from the groups + whatever canon artifacts exist. Because ``cast.json`` is
  rewritten after every major (majors without a canon artifact stay ``null``, exactly like
  minors), a kill mid-phase leaves a schema-valid file and resumes losing ≤1 unit.

``cast-canonicalize`` failures follow the runner taxonomy via :class:`TtsClient`: 503 →
``waiting_gpu`` (``cast_running`` is a GPU state — the S5 state addition), 422 →
``failed_units`` (that major stays ``null``), 400/404/413 → job ``failed``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ... import schemas
from ..job import Job, JobState
from ..reduce_cast import reduce_cast
from ..tts_client import TtsClient
from .base import Unit
from .p1_mentions import mentions_dir


def _cast_dir(cfg: Any, job: Job) -> Path:
    return cfg.work_dir / job.book_id / "cast"


def _groups_path(cfg: Any, job: Job) -> Path:
    return _cast_dir(cfg, job) / "groups.json"


def _canon_dir(cfg: Any, job: Job) -> Path:
    return _cast_dir(cfg, job) / "canon"


def _cast_json_path(cfg: Any, job: Job) -> Path:
    return cfg.work_dir / job.book_id / "cast.json"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _load_page_mentions(cfg: Any, job: Job) -> list[dict[str, Any]]:
    """All ``mentions/{page}.json`` as ``reduce_cast`` input, in page order."""
    mdir = mentions_dir(cfg, job)
    pages: list[dict[str, Any]] = []
    if not mdir.is_dir():
        return pages
    for path in sorted(mdir.glob("*.json")):
        data = _read_json(path)
        pages.append({"page_id": path.stem, "mentions": data.get("mentions", [])})
    return pages


def assemble_cast_json(cfg: Any, job: Job) -> dict[str, Any]:
    """Build ``cast.json`` from ``groups.json`` + any ``canon/{slug}.json``; validate + write.

    Idempotent: safe to call after the reduce (no canon yet → all ``null``) and after every
    canonicalized major. Always writes a schema-valid document.
    """
    groups = _read_json(_groups_path(cfg, job))
    canon_dir = _canon_dir(cfg, job)
    characters: list[dict[str, Any]] = []
    for g in groups:
        canon_path = canon_dir / f"{g['slug']}.json"
        canon = _read_json(canon_path) if canon_path.is_file() else None
        characters.append(
            {
                "slug": g["slug"],
                "name": g["name"],
                "aliases": g["aliases"],
                "mention_pages": g["mention_pages"],
                "major": g["major"],
                "visual_description": canon["visual_description"] if canon else None,
                "one_line": canon["one_line"] if canon else "",
                "tags": canon["tags"] if canon else [],
                "portrait": None,  # portraits are rendered in P7 (S10), not here
                "edited_by_human": False,
            }
        )
    doc = {"characters": characters}
    schemas.validate("cast", doc)
    _write_json(_cast_json_path(cfg, job), doc)
    return doc


class CastReduce:
    """P2a: reduce per-page mentions into grouped cast entries (CPU, one unit)."""

    name = "p2_reduce"
    from_state = JobState.MENTIONS_DONE
    to_state = JobState.CAST_RUNNING
    is_gpu = False

    def units(self, job: Job, cfg: Any) -> list[Unit]:
        return [Unit(id="reduce")]

    def unit_done(self, job: Job, cfg: Any, unit: Unit) -> bool:
        path = _groups_path(cfg, job)
        if not path.is_file():
            return False
        try:
            _read_json(path)
            return True
        except json.JSONDecodeError:
            return False

    def run_unit(self, job: Job, cfg: Any, unit: Unit) -> None:
        groups = reduce_cast(_load_page_mentions(cfg, job))
        _write_json(_groups_path(cfg, job), groups)
        assemble_cast_json(cfg, job)  # initial cast.json, all visual_description null


class CastCanonicalize:
    """P2b: canonicalize each major character (GPU-LLM, unit = major)."""

    name = "p2_canonicalize"
    from_state = JobState.CAST_RUNNING
    to_state = JobState.CAST_DONE
    is_gpu = True

    def units(self, job: Job, cfg: Any) -> list[Unit]:
        path = _groups_path(cfg, job)
        if not path.is_file():
            return []
        groups = _read_json(path)
        return [Unit(id=g["slug"], payload=g) for g in groups if g.get("major")]

    def unit_done(self, job: Job, cfg: Any, unit: Unit) -> bool:
        path = _canon_dir(cfg, job) / f"{unit.id}.json"
        if not path.is_file():
            return False
        try:
            _read_json(path)
            return True
        except json.JSONDecodeError:
            return False

    async def run_unit(self, job: Job, cfg: Any, unit: Unit) -> None:
        group = unit.payload or self._group_for(cfg, job, unit.id)
        options: dict[str, Any] = {
            "name": group["name"],
            "aliases": group["aliases"],
            "descriptors": group["descriptors"],
        }
        era = job.bake_config.get("era")
        genre = job.bake_config.get("genre")
        if era:
            options["era"] = era
        if genre:
            options["genre"] = genre

        output = await TtsClient(cfg).transform("cast-canonicalize", "", options)
        _write_json(_canon_dir(cfg, job) / f"{unit.id}.json", output)
        assemble_cast_json(cfg, job)  # fold this major into cast.json

    def _group_for(self, cfg: Any, job: Job, slug: str) -> dict[str, Any]:
        for g in _read_json(_groups_path(cfg, job)):
            if g["slug"] == slug:
                return g
        raise KeyError(slug)  # pragma: no cover - defensive
