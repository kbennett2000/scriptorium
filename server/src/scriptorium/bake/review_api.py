"""Review-gate admin API (DESIGN §11.1 review rows, §8 reselect, §4.3 edits).

The endpoints a human uses between P5 (``prompts_draft``) and render: inspect the drafted shot
list, edit prompts / cast, add or drop plates manually, re-turn the density knob, and **approve**
— the gate that enforces invariant #4 ("no plate rendered before approval"). Approve refuses if any
plate that will render lacks a prompt artifact.

All handlers resolve config per-request via :func:`load_config` (like :mod:`.api`), read/write the
``work/{book_id}/`` artifacts directly, and re-validate every mutated artifact against its schema
before persisting. Nothing here renders, publishes, or wraps prompts with style — that is S10.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import schemas
from ..config import load_config
from ..selection.engine import PRESETS, PageScore, select
from ..selection.reselect import reselect
from ..styles import load_styles
from . import job as jobmod
from .job import Job, JobState

router = APIRouter(prefix="/api/admin")

# States in which the review artifacts exist and edits are still pre-approval (§11.1).
_REVIEW_STATES = (JobState.PROMPTS_DRAFT, JobState.IN_REVIEW)
# States in which the review payload is readable (pre-approval edit window + the locked views).
_READABLE_STATES = (
    JobState.PROMPTS_DRAFT, JobState.IN_REVIEW, JobState.APPROVED, JobState.RENDERING,
)
_GUTENDEX = "https://gutendex.com/books"


# --- request bodies ---------------------------------------------------------


class PromptEditBody(BaseModel):
    edited_prompt: str | None = None


class SelectionEditBody(BaseModel):
    add: list[str] = []
    remove: list[str] = []


class CastEditBody(BaseModel):
    visual_description: str | None = None
    one_line: str | None = None


class ReselectBody(BaseModel):
    density_preset: str


# --- helpers ----------------------------------------------------------------


def _require(book_id: str) -> Job:
    job = jobmod.load(load_config(), book_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"no such book {book_id!r}")
    return job


def _book_dir(book_id: str) -> Path:
    return load_config().work_dir / book_id


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _page_scores(book_id: str) -> list[PageScore]:
    pages_dir = _book_dir(book_id) / "pages"
    scores: list[PageScore] = []
    for p in sorted(pages_dir.glob("*.json")):
        doc = _read_json(p)
        ledger = doc.get("ledger") or {}
        scores.append(PageScore(
            seq=doc["seq"], page_id=doc["id"], chapter=doc.get("chapter", 1),
            scene_changed=bool(ledger.get("scene_changed", False)),
            visual_salience=float(ledger.get("visual_salience", 0.0)),
        ))
    return scores


def _page_salience(book_id: str, page_id: str) -> float:
    path = _book_dir(book_id) / "pages" / f"{page_id}.json"
    if not path.is_file():
        return 0.0
    return float((_read_json(path).get("ledger") or {}).get("visual_salience", 0.0))


def _text_download_url(formats: dict) -> str | None:
    """Prefer the utf-8 plain-text link, else any ``text/plain`` variant (§5.1)."""
    if formats.get("text/plain; charset=utf-8"):
        return formats["text/plain; charset=utf-8"]
    for mime, url in formats.items():
        if mime.startswith("text/plain"):
            return url
    return None


# --- endpoints --------------------------------------------------------------


@router.get("/gutendex")
def gutendex(q: str = Query("")) -> dict:
    """Proxy a Gutendex search for the wizard (§11.1). Degrades to 502; never 500."""
    if not q.strip():
        return {"results": []}
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(_GUTENDEX, params={"search": q})
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"gutendex unreachable: {exc}") from exc
    results = [
        {
            "id": b.get("id"),
            "title": b.get("title"),
            "authors": [a.get("name") for a in b.get("authors", [])],
            "download_url": _text_download_url(b.get("formats", {})),
        }
        for b in data.get("results", [])[:20]
    ]
    return {"results": results}


@router.get("/styles")
def styles() -> dict:
    """The style catalog (``data/styles.json``) for the wizard's style picker (§9)."""
    return load_styles()


@router.get("/books/{book_id}/review")
def get_review(book_id: str) -> dict:
    """The full review payload: selection + prompts + cast + warnings + per-page beats (§11.1)."""
    job = _require(book_id)
    book = _book_dir(book_id)
    sel_path = book / "selection.json"
    prompts_dir = book / "prompts"
    if not sel_path.is_file() or not prompts_dir.is_dir():
        raise HTTPException(status_code=409, detail=f"no review yet (state={job.state})")

    prompts = [_read_json(p) for p in sorted(prompts_dir.glob("*.json"))]
    cast_path = book / "cast.json"
    cast = _read_json(cast_path) if cast_path.is_file() else {"characters": []}

    beats: dict[str, str] = {}
    pages_dir = book / "pages"
    if pages_dir.is_dir():
        for p in sorted(pages_dir.glob("*.json")):
            doc = _read_json(p)
            beat = (doc.get("ledger") or {}).get("best_visual_beat")
            if beat:
                beats[doc["id"]] = beat

    return {
        "book_id": book_id,
        "state": job.state,
        "selection": _read_json(sel_path),
        "cast": cast,
        "prompts": prompts,
        "warnings": job.warnings,
        "prompt_warnings": job.prompt_warnings,
        "failed_units": job.failed_units,
        "beats": beats,
    }


@router.put("/books/{book_id}/review/prompt/{page_id}")
def edit_prompt(book_id: str, page_id: str, body: PromptEditBody) -> dict:
    """Persist ``edited_prompt`` and recompute ``final_subject_prompt`` (§4.3, §11.1)."""
    cfg = load_config()
    job = _require(book_id)
    if job.state not in _REVIEW_STATES:
        raise HTTPException(status_code=409,
                            detail=f"prompts editable only pre-approval (state={job.state})")
    path = cfg.work_dir / book_id / "prompts" / f"{page_id}.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"no prompt for {page_id!r}")
    doc = _read_json(path)
    doc["edited_prompt"] = body.edited_prompt
    doc["final_subject_prompt"] = (
        body.edited_prompt if body.edited_prompt is not None else doc["derived"]["prompt"]
    )
    schemas.validate("prompt", doc)
    _write_json(path, doc)
    return doc


@router.put("/books/{book_id}/review/selection")
def edit_selection(book_id: str, body: SelectionEditBody) -> dict:
    """Manual plate add/remove (§8 manual overrides, §11.3)."""
    cfg = load_config()
    job = _require(book_id)
    if job.state not in _REVIEW_STATES:
        raise HTTPException(status_code=409,
                            detail=f"selection editable only pre-approval (state={job.state})")
    path = cfg.work_dir / book_id / "selection.json"
    doc = _read_json(path)
    plates = doc["plates"]
    by_id = {p["page_id"]: p for p in plates}
    rev = max((p["added_in_revision"] for p in plates), default=1)

    # Removals: a rendered plate retires (files kept); a never-rendered one is dropped outright
    # (its prompt file is intentionally left in place so re-adding round-trips — §11.3).
    for page_id in body.remove:
        plate = by_id.get(page_id)
        if plate is None:
            continue
        if plate["status"] == "rendered":
            plate["status"] = "retired"
        else:
            plates = [p for p in plates if p["page_id"] != page_id]
            by_id.pop(page_id, None)

    # Additions: 4-digit page ids only (pseudo-plates are not tracked in selection.json).
    for page_id in body.add:
        if not (page_id.isdigit() and len(page_id) == 4):
            raise HTTPException(status_code=400, detail=f"not a page id: {page_id!r}")
        if not (cfg.work_dir / book_id / "pages" / f"{page_id}.json").is_file():
            raise HTTPException(status_code=404, detail=f"no such page {page_id!r}")
        existing = by_id.get(page_id)
        if existing is not None:
            if existing["status"] == "retired":
                existing["status"] = "selected"
            continue
        entry = {
            "page_id": page_id, "reason": "manual",
            "salience": _page_salience(book_id, page_id),
            "status": "selected", "added_in_revision": rev,
        }
        plates.append(entry)
        by_id[page_id] = entry

    doc["plates"] = sorted(plates, key=lambda p: p["page_id"])
    schemas.validate("selection", doc)
    _write_json(path, doc)
    return doc


@router.put("/books/{book_id}/review/cast/{slug}")
def edit_cast(book_id: str, slug: str, body: CastEditBody) -> dict:
    """Edit a character's ``visual_description``/``one_line`` → sets ``edited_by_human`` (§4.3)."""
    cfg = load_config()
    job = _require(book_id)
    if job.state not in _REVIEW_STATES:
        raise HTTPException(status_code=409,
                            detail=f"cast editable only pre-approval (state={job.state})")
    path = cfg.work_dir / book_id / "cast.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="no cast")
    doc = _read_json(path)
    char = next((c for c in doc.get("characters", []) if c.get("slug") == slug), None)
    if char is None:
        raise HTTPException(status_code=404, detail=f"no character {slug!r}")
    if body.visual_description is not None:
        char["visual_description"] = body.visual_description
    if body.one_line is not None:
        char["one_line"] = body.one_line
    char["edited_by_human"] = True
    schemas.validate("cast", doc)
    _write_json(path, doc)
    return char


@router.post("/books/{book_id}/approve")
def approve(book_id: str) -> dict:
    """Lock the shot list → ``approved``. Refuses if any renderable plate lacks a prompt (§11.1)."""
    cfg = load_config()
    job = _require(book_id)
    if job.state not in _REVIEW_STATES:
        raise HTTPException(status_code=409, detail=f"cannot approve from {job.state}")
    book = cfg.work_dir / book_id
    sel = _read_json(book / "selection.json")
    prompts_dir = book / "prompts"

    # Every plate that will render (selected/approved, or any manual) must already have a prompt.
    missing = sorted({
        p["page_id"] for p in sel["plates"]
        if (p["status"] in ("selected", "approved") or p.get("reason") == "manual")
        and not (prompts_dir / f"{p['page_id']}.json").is_file()
    })
    if missing:
        raise HTTPException(
            status_code=422,
            detail={"error": "selected plates missing prompts", "page_ids": missing},
        )

    for plate in sel["plates"]:
        if plate["status"] == "selected":
            plate["status"] = "approved"
    schemas.validate("selection", sel)
    _write_json(book / "selection.json", sel)

    if job.state == JobState.PROMPTS_DRAFT:
        job.transition(JobState.IN_REVIEW)  # transient waypoint (see plan / CYCLE-LOG S9a)
    job.transition(JobState.APPROVED)
    job.save(cfg)
    return job.to_dict()


@router.post("/books/{book_id}/reselect")
def do_reselect(book_id: str, body: ReselectBody) -> dict:
    """Re-turn the density knob → §8 re-selection, then re-queue P5 for newcomers (§11.1)."""
    cfg = load_config()
    job = _require(book_id)
    if job.state not in (JobState.SELECTED, *_REVIEW_STATES):
        raise HTTPException(status_code=409, detail=f"cannot reselect from {job.state}")
    if body.density_preset not in PRESETS:
        raise HTTPException(status_code=400, detail=f"unknown preset {body.density_preset!r}")

    book = cfg.work_dir / book_id
    structure = _read_json(book / "structure.json")
    params = PRESETS[body.density_preset]
    fresh = select(_page_scores(book_id), structure, params)

    sel_path = book / "selection.json"
    existing = _read_json(sel_path)["plates"] if sel_path.is_file() else []
    rev = max((p["added_in_revision"] for p in existing), default=1)
    # Pre-publish there is no revision to bump — newcomers join the current revision (S10 owns the
    # post-publish additive revision flow). Prompt files are kept so already-derived plates skip P5.
    merged = reselect(fresh, existing, revision=rev)
    doc = {"preset": body.density_preset, "params": params.as_dict(), "plates": merged}
    schemas.validate("selection", doc)
    _write_json(sel_path, doc)

    # Deliberate re-queue: reset straight to `selected` (a pipeline re-entry, not a forward edge)
    # so the runner re-runs P5, deriving only the newcomers (P5 unit_done skips existing prompts).
    job.state = JobState.SELECTED
    job.prev_state = None
    job.save(cfg)
    return doc


@router.get("/books/{book_id}/plate-image/{page_id}.png")
def plate_image(book_id: str, page_id: str) -> FileResponse:
    """Serve a work-dir plate PNG for the post-render view (admin-only, pre-publish)."""
    cfg = load_config()
    _require(book_id)
    base = (cfg.work_dir / book_id / "images" / "plates").resolve()
    target = (base / f"{page_id}.png").resolve()
    if not target.is_relative_to(base):
        raise HTTPException(status_code=400, detail="bad path")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="no image")
    return FileResponse(target, media_type="image/png")
