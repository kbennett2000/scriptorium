"""P4 selection phase driven through the real runner (DESIGN §8, §7.3).

P4 is CPU-only, so — unlike the P1/P2/P3 tests — there is no respx/TTS machinery: pages are
seeded already carrying a merged ``ledger`` (as P3 leaves them), the runner is driven to
``selected``, and assertions are made on ``work/b/selection.json``. The final test is the S7
acceptance "fixture pipeline" check: merge the six S6 ``scene-update`` fixtures onto the six S3
bundle pages and confirm the produced ``selection.json`` is schema-valid and obeys the §8
invariants (values may legitimately differ from the hand-written bundle fixture).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from scriptorium import schemas
from scriptorium.bake import job as jobmod
from scriptorium.bake.job import Job, JobState
from scriptorium.bake.phases.p4_select import P4Select
from scriptorium.bake.runner import Runner
from scriptorium.config import Config

_FIX = Path(__file__).parent / "fixtures"
_BUNDLE = _FIX / "bundle"
_SCENE = _FIX / "tts" / "scene-update"


def _cfg(tmp_path) -> Config:
    return Config(
        data_dir=tmp_path, port=8720, tts_url=None, imagegen_url=None, gpu_mac=None,
        gpu_wol_enabled=False, runner_tick_s=1, shared_dir=tmp_path,
    )


async def _gate_up(_cfg: Config) -> bool:
    return True


async def _noop_sleep(_s: float) -> None:
    return None


def _runner(cfg: Config) -> Runner:
    return Runner(cfg, [P4Select()], sleep=_noop_sleep, wake=lambda _c: None, gpu_gate=_gate_up)


def _ledger(scene_changed: bool, salience: float) -> dict[str, Any]:
    return {
        "location": "", "time_of_day": "unknown", "atmosphere": "", "present": [],
        "scene_changed": scene_changed, "visual_salience": salience,
        "best_visual_beat": "", "carry_notes": "",
    }


def _page(pid: str, seq: int, chapter: int, *, scene: bool, salience: float) -> dict[str, Any]:
    return {
        "id": pid, "seq": seq, "chapter": chapter, "text": f"PAGE {pid}", "word_count": 2,
        "ledger": _ledger(scene, salience),
    }


def _write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _seed_pages(cfg: Config, pages: list[dict], structure: dict, *,
                bake_config: dict | None = None) -> Job:
    book = cfg.work_dir / "b"
    for page in pages:
        _write(book / "pages" / f"{page['id']}.json", page)
    _write(book / "structure.json", structure)
    job = Job(id="b", book_id="b", state=JobState.LEDGER_DONE, started=True,
              bake_config=bake_config or {"density_preset": "classic"})
    job.save(cfg)
    return job


def _drive(cfg: Config, runner: Runner, *, stop_states: set[str], max_ticks: int = 8) -> Job:
    for _ in range(max_ticks):
        asyncio.run(runner.tick())
        job = jobmod.load(cfg, "b")
        if job.state in stop_states:
            return job
    return jobmod.load(cfg, "b")


def _selection(cfg: Config) -> dict:
    return json.loads((cfg.work_dir / "b" / "selection.json").read_text("utf-8"))


# A 12-page, 3-chapter synthetic book (≥8 so the presets apply, not tiny-work). Openers
# 0001/0005/0009; a scene boundary at 0007 that is ≥ min_gap from both surrounding openers.
_PAGES = [
    _page("0001", 1, 1, scene=False, salience=0.70),
    _page("0002", 2, 1, scene=False, salience=0.40),
    _page("0003", 3, 1, scene=False, salience=0.55),
    _page("0004", 4, 1, scene=False, salience=0.30),
    _page("0005", 5, 2, scene=False, salience=0.65),
    _page("0006", 6, 2, scene=False, salience=0.45),
    _page("0007", 7, 2, scene=True, salience=0.90),
    _page("0008", 8, 2, scene=False, salience=0.35),
    _page("0009", 9, 3, scene=False, salience=0.60),
    _page("0010", 10, 3, scene=False, salience=0.50),
    _page("0011", 11, 3, scene=False, salience=0.42),
    _page("0012", 12, 3, scene=False, salience=0.48),
]
_STRUCTURE = {
    "chapters": [
        {"index": 1, "title": "I", "page_ids": ["0001", "0002", "0003", "0004"]},
        {"index": 2, "title": "II", "page_ids": ["0005", "0006", "0007", "0008"]},
        {"index": 3, "title": "III", "page_ids": ["0009", "0010", "0011", "0012"]},
    ]
}


def test_phase_writes_schema_valid_selection(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _seed_pages(cfg, _PAGES, _STRUCTURE)

    job = _drive(cfg, _runner(cfg), stop_states={JobState.SELECTED})
    assert job.state == JobState.SELECTED

    doc = _selection(cfg)
    schemas.validate("selection", doc)
    assert doc["preset"] == "classic"
    assert doc["params"] == {
        "min_gap": 2, "max_gap": 6, "salience_floor": 0.55,
        "chapter_open": True, "scene_boundary": True,
    }

    by_id = {p["page_id"]: p for p in doc["plates"]}
    # Every chapter opener is present as chapter_open.
    for opener in ("0001", "0005", "0009"):
        assert by_id[opener]["reason"] == "chapter_open"
    # The scene boundary at 0007 (≥ min_gap from both openers) survives.
    assert by_id["0007"]["reason"] == "scene_boundary"
    # All plates fresh: selected, revision 1; reasons valid; min_gap holds.
    assert all(p["status"] == "selected" and p["added_in_revision"] == 1 for p in doc["plates"])
    ids = [int(p["page_id"]) for p in doc["plates"]]
    assert all(b - a >= 2 for a, b in zip(ids, ids[1:], strict=False))


def test_phase_respects_density_preset_from_bake_config(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _seed_pages(cfg, _PAGES, _STRUCTURE, bake_config={"density_preset": "sparse"})

    job = _drive(cfg, _runner(cfg), stop_states={JobState.SELECTED})
    assert job.state == JobState.SELECTED

    doc = _selection(cfg)
    schemas.validate("selection", doc)
    assert doc["preset"] == "sparse"
    assert doc["params"]["scene_boundary"] is False
    # sparse disables scene boundaries → no scene_boundary plates.
    assert all(p["reason"] != "scene_boundary" for p in doc["plates"])


def test_phase_is_idempotent_when_selection_exists(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    _seed_pages(cfg, _PAGES, _STRUCTURE)
    # A pre-existing (different) selection.json must not be overwritten — unit_done short-circuits.
    sentinel = {
        "preset": "sparse",
        "params": {"min_gap": 4, "max_gap": 12, "salience_floor": 0.85,
                   "chapter_open": True, "scene_boundary": False},
        "plates": [{"page_id": "0002", "reason": "fill", "salience": 0.9,
                    "status": "rendered", "added_in_revision": 1}],
    }
    _write(cfg.work_dir / "b" / "selection.json", sentinel)

    job = _drive(cfg, _runner(cfg), stop_states={JobState.SELECTED})
    assert job.state == JobState.SELECTED
    assert _selection(cfg) == sentinel  # untouched


def test_fixture_pipeline_selection_is_schema_valid(tmp_path) -> None:
    """S7 acceptance: run P4 over the bundle book with the S6 scene-update ledgers merged in.

    Values may legitimately differ from ``bundle/selection.json`` (this test merges the hand-written
    scene fixtures, not the generic ones that produced the committed bundle), so we assert schema +
    §8 invariants, not equality.
    """
    cfg = _cfg(tmp_path)
    structure = json.loads((_BUNDLE / "structure.json").read_text("utf-8"))
    pages = []
    for page_file in sorted((_BUNDLE / "pages").glob("*.json")):
        page = json.loads(page_file.read_text("utf-8"))
        env = json.loads((_SCENE / f"{page['id']}.json").read_text("utf-8"))
        page["ledger"] = env["output"]  # merge the S6 ledger as P3 would
        pages.append(page)
    _seed_pages(cfg, pages, structure)

    job = _drive(cfg, _runner(cfg), stop_states={JobState.SELECTED})
    assert job.state == JobState.SELECTED

    doc = _selection(cfg)
    schemas.validate("selection", doc)  # the acceptance box
    # §8 invariants hold on the pipeline output.
    ids = [int(p["page_id"]) for p in doc["plates"]]
    assert ids == sorted(ids)
    assert all(b - a >= doc["params"]["min_gap"] for a, b in zip(ids, ids[1:], strict=False))
    assert all(p["reason"] in {"chapter_open", "scene_boundary", "fill"} for p in doc["plates"])
    # Every chapter opener is selected.
    openers = {ch["page_ids"][0] for ch in structure["chapters"]}
    assert openers <= {p["page_id"] for p in doc["plates"]}

    # The committed fixture selection.json is now genuine P4 output (S10b regenerated the bundle via
    # the real pipeline), so the S7 hand-written min_gap divergence is gone — it honours §8 too.
    committed = json.loads((_BUNDLE / "selection.json").read_text("utf-8"))
    schemas.validate("selection", committed)
    c_ids = sorted(int(p["page_id"]) for p in committed["plates"])
    c_gap = committed["params"]["min_gap"]
    assert all(b - a >= c_gap for a, b in zip(c_ids, c_ids[1:], strict=False))
