"""P3 — strictly-sequential scene ledger (DESIGN §7.1/§7.3, transform ``scene-update``).

One ``scene-update`` call per page, **in strict page order**, threading each returned ledger
into the next call's ``prior_ledger``. The single pass produces both the continuity ledger and
the selection scores (``visual_salience`` / ``scene_changed``) that P4 consumes.

Two phases, mirroring P1/P2's enter/run split so the GPU half sits on a ``*_running`` state,
**plus P3's contiguity + gap rule**:

- :class:`LedgerEnter` — CPU claim ``cast_done → ledger_running`` (zero units), identical in
  spirit to :class:`~scriptorium.bake.phases.p1_mentions.MentionsEnter`: a GPU phase's
  ``from_state`` must be a GPU state, and ``cast_done`` is not one.
- :class:`LedgerScenes` — GPU phase ``ledger_running → ledger_done``. Its units are the pages
  in id order **followed by one trailing** :data:`MERGE_UNIT_ID` **pseudo-unit**. Each page unit
  writes ``ledgers/{page_id}.json`` (the verbatim ``scene-update`` output). The merge unit runs
  only *after* every page unit in the pass has succeeded or ladder-failed — the runner parks on
  ``waiting_gpu`` *before* reaching it if a page hits 503 — so the gap rule is applied at **phase
  end, not unit time**, and a later retry across an interrupted pass can still fill the real
  ledger first.

**Threading semantics (deliberate):** a page's ``prior_ledger`` is the *last successful* stored
ledger before it (the greatest earlier page-id that has a ``ledgers/*.json`` artifact), or
``null`` on the first page / after only-gaps. Generation therefore threads across a failed page
from the last real ledger — it never threads from an *inherited* gap ledger. The inherited gap
ledger exists only in the merged ``pages/*.json`` (provenance), produced by the merge unit; e.g.
if page 3 fails, page 4 is generated threading from page 2, and page 3's *merged* ledger is a
copy of page 2's with ``carry_notes`` annotated ``" [ledger gap]"``.

``scene-update`` failures follow the runner taxonomy via :class:`TtsClient`: 503/connection →
``waiting_gpu`` (``ledger_running`` is a GPU state), 422 → ``failed_units`` (that page left
ledger-less, filled by the gap rule at merge), 400/404/413 → job ``failed``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ... import schemas
from ..job import Job, JobState
from ..tts_client import TtsClient
from .base import Unit

# The trailing pseudo-unit that performs the phase-end merge (see module docstring). Its id is
# non-numeric so it can never collide with a 4-digit page id.
MERGE_UNIT_ID = "merge"

# §7.4 carry_notes cap; the annotation is appended within this limit.
_CARRY_NOTES_MAX = 200
_GAP_ANNOTATION = " [ledger gap]"

# A page with this many words or fewer gets the neutral ledger (no model call, salience 0) —
# a backstop for a stray divider/contents line. Kept far below a real one-sentence page so it
# never neutralizes genuine content (e.g. "Ivan was called to give evidence." — 6 words).
_NEUTRAL_LEDGER_MAX_WORDS = 3

# A neutral, schema-valid ledger for a *leading* gap (page 1 itself failed, so there is no
# predecessor to inherit). The page schema treats the ledger as an opaque object, so only the
# shape matters to downstream consumers (P4 reads scene_changed / visual_salience).
_NEUTRAL_LEDGER: dict[str, Any] = {
    "location": "",
    "time_of_day": "unknown",
    "atmosphere": "",
    "present": [],
    "scene_changed": False,
    "visual_salience": 0.0,
    "best_visual_beat": "",
    "carry_notes": _GAP_ANNOTATION.strip(),
}


def _pages_dir(cfg: Any, job: Job) -> Path:
    return cfg.work_dir / job.book_id / "pages"


def ledgers_dir(cfg: Any, job: Job) -> Path:
    return cfg.work_dir / job.book_id / "ledgers"


def _cast_json_path(cfg: Any, job: Job) -> Path:
    return cfg.work_dir / job.book_id / "cast.json"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _page_ids(cfg: Any, job: Job) -> list[str]:
    """All page ids in bundle order (zero-padded ids sort correctly)."""
    pages = _pages_dir(cfg, job)
    if not pages.is_dir():
        return []
    return [p.stem for p in sorted(pages.glob("*.json"))]


def _cast_names(cfg: Any, job: Job) -> list[str]:
    """Canonical cast names for the ``scene-update`` options (§7.4, cap 40)."""
    path = _cast_json_path(cfg, job)
    if not path.is_file():
        return []
    doc = _read_json(path)
    return [c["name"] for c in doc.get("characters", [])][:40]


def _prior_ledger(cfg: Any, job: Job, page_id: str, page_ids: list[str]) -> dict | None:
    """The last *successful* stored ledger before ``page_id`` (§7.3 threading), or ``None``.

    Scans earlier page ids in descending order and returns the first ledger artifact that
    exists — so generation threads across a gap page from the last real ledger, never from an
    inherited one.
    """
    ldir = ledgers_dir(cfg, job)
    idx = page_ids.index(page_id)
    for earlier in reversed(page_ids[:idx]):
        art = ldir / f"{earlier}.json"
        if art.is_file():
            try:
                return _read_json(art)
            except json.JSONDecodeError:  # pragma: no cover - defensive
                continue
    return None


class LedgerEnter:
    """Zero-unit CPU transition ``cast_approved → ledger_running`` (the enter-running pattern).

    Starts from ``cast_approved`` (not ``cast_done``) so the ledger — and everything downstream
    that reads the cast — runs only after the cast-review gate has been approved (ADR-0032).
    """

    name = "ledger_enter"
    from_state = JobState.CAST_APPROVED
    to_state = JobState.LEDGER_RUNNING
    is_gpu = False

    def units(self, job: Job, cfg: Any) -> list[Unit]:
        return []

    def unit_done(self, job: Job, cfg: Any, unit: Unit) -> bool:  # pragma: no cover
        return True  # no units, so never consulted

    def run_unit(self, job: Job, cfg: Any, unit: Unit) -> None:  # pragma: no cover
        return None


class LedgerScenes:
    """P3: thread a scene ledger through the book, then merge into pages (GPU, unit = page)."""

    name = "p3_ledger"
    from_state = JobState.LEDGER_RUNNING
    to_state = JobState.LEDGER_DONE
    is_gpu = True

    def units(self, job: Job, cfg: Any) -> list[Unit]:
        page_ids = _page_ids(cfg, job)
        if not page_ids:
            return []
        # Pages in strict order, then the trailing merge pseudo-unit (phase-end gap rule).
        return [Unit(id=pid) for pid in page_ids] + [Unit(id=MERGE_UNIT_ID)]

    def unit_done(self, job: Job, cfg: Any, unit: Unit) -> bool:
        if unit.id == MERGE_UNIT_ID:
            return self._merge_done(cfg, job)
        path = ledgers_dir(cfg, job) / f"{unit.id}.json"
        if not path.is_file():
            return False
        try:
            _read_json(path)
            return True
        except json.JSONDecodeError:
            return False

    async def run_unit(self, job: Job, cfg: Any, unit: Unit) -> None:
        if unit.id == MERGE_UNIT_ID:
            self._merge(cfg, job)  # pure I/O; no TTS call
            return
        page_ids = _page_ids(cfg, job)
        page = _read_json(_pages_dir(cfg, job) / f"{unit.id}.json")
        if len(page["text"].split()) <= _NEUTRAL_LEDGER_MAX_WORDS:
            # A blank or near-empty page (e.g. a stray section-divider / contents line that
            # survived ingest) has nothing to describe; asking the model would hallucinate a
            # beat and salience, which would then get illustrated. Give it a neutral ledger
            # (salience 0.0, empty beat) so it is never selected. The ingest table-of-contents
            # pruning (ADR-0018) is the primary defense; this is a conservative backstop whose
            # threshold stays well below any real one-sentence page.
            _write_json(ledgers_dir(cfg, job) / f"{unit.id}.json", dict(_NEUTRAL_LEDGER))
            return
        options: dict[str, Any] = {
            "prior_ledger": _prior_ledger(cfg, job, unit.id, page_ids),
            "cast_names": _cast_names(cfg, job),
        }
        era = job.bake_config.get("era")
        if era:
            options["era"] = era

        output = await TtsClient(cfg).transform("scene-update", page["text"], options)
        _write_json(ledgers_dir(cfg, job) / f"{unit.id}.json", output)

    # --- phase-end merge (gap rule) -----------------------------------------

    def _merge_done(self, cfg: Any, job: Job) -> bool:
        """True iff every page json already carries a ``ledger`` (idempotent checkpoint)."""
        for pid in _page_ids(cfg, job):
            page = _read_json(_pages_dir(cfg, job) / f"{pid}.json")
            if "ledger" not in page:
                return False
        return True

    def _merge(self, cfg: Any, job: Job) -> None:
        """Write each page's ledger into ``pages/{id}.json``, applying the §7.3 gap rule.

        Iterates pages in order carrying the running ``prev`` ledger. A page with a stored
        ledger uses it verbatim; a page whose ledger permanently failed inherits a copy of
        ``prev`` with ``carry_notes`` annotated ``" [ledger gap]"``. Applied here, at phase
        end, rather than at unit time — so a late retry (on an interrupted pass) fills the real
        ledger before this ever runs.
        """
        ldir = ledgers_dir(cfg, job)
        prev: dict | None = None
        for pid in _page_ids(cfg, job):
            art = ldir / f"{pid}.json"
            if art.is_file():
                ledger = _read_json(art)
            else:
                ledger = self._inherit(prev)
            page_path = _pages_dir(cfg, job) / f"{pid}.json"
            page = _read_json(page_path)
            page["ledger"] = ledger
            schemas.validate("page", page)
            _write_json(page_path, page)
            prev = ledger

    def _inherit(self, prev: dict | None) -> dict:
        """A gap page's ledger: a copy of ``prev`` (or a neutral ledger) + the gap annotation."""
        if prev is None:  # leading gap: no predecessor to inherit
            return dict(_NEUTRAL_LEDGER)
        inherited = dict(prev)
        notes = (inherited.get("carry_notes", "") or "") + _GAP_ANNOTATION
        inherited["carry_notes"] = notes[:_CARRY_NOTES_MAX]
        return inherited
