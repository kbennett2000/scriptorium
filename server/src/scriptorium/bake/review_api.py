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
import secrets
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import schemas
from ..config import Config, load_config
from ..render.imagegen import ImagegenClient, RealImagegenClient
from ..selection.engine import PRESETS, PageScore, effective_params, select
from ..selection.reselect import reselect
from ..selection.segment import expand_choices
from ..styles import load_styles
from . import job as jobmod
from .approve import ApprovalBlocked, approve_job, approve_portraits
from .job import Job, JobState
from .phases.base import GpuUnavailable
from .phases.p5_prompts import PORTRAIT_PREFIX, rederive_portrait_prompt
from .phases.p7_render import build_cast_index, render_plate, resolve_character
from .phases.p8_publish import regen_published_plate

router = APIRouter(prefix="/api/admin")

# States in which the review artifacts exist and edits are still pre-approval (§11.1).
_REVIEW_STATES = (JobState.PROMPTS_DRAFT, JobState.IN_REVIEW)
# Prompt/cast edits are also allowed at the optional portrait gate (ADR-0025), where a human tunes
# and regenerates portraits before the page plates draw.
_PORTRAIT_EDIT_STATES = (*_REVIEW_STATES, JobState.PORTRAITS_REVIEW)
# States in which the review payload is readable (pre-approval edit window + the locked views).
_READABLE_STATES = (
    JobState.PROMPTS_DRAFT, JobState.IN_REVIEW, JobState.APPROVED,
    JobState.PORTRAITS_RENDERING, JobState.PORTRAITS_REVIEW, JobState.RENDERING,
)
# Trailing slash matters: gutendex.com 301-redirects /books?... -> /books/?..., so we hit the
# canonical URL directly (and the client below follows redirects as a belt-and-braces guard).
_GUTENDEX = "https://gutendex.com/books/"


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


def _page_texts(book_id: str) -> dict[str, str]:
    """page_id -> canonical text, for the pictures-per-scene expansion on re-selection."""
    pages_dir = _book_dir(book_id) / "pages"
    return {doc["id"]: doc.get("text", "")
            for doc in (_read_json(p) for p in sorted(pages_dir.glob("*.json")))}


def _page_salience(book_id: str, page_id: str) -> float:
    path = _book_dir(book_id) / "pages" / f"{page_id}.json"
    if not path.is_file():
        return 0.0
    return float((_read_json(path).get("ledger") or {}).get("visual_salience", 0.0))


def _imagegen_client(cfg: Config) -> ImagegenClient:
    """The imagegen client for the regen endpoint. Indirected so tests inject a fake."""
    return RealImagegenClient(cfg)


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
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
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
        # True while the plates are S9-stub placeholders; the real render (P7) clears it, flipping
        # off the post-render "placeholder" banner (S10b).
        "render_stub": job.render_stub,
        "portrait_anchor_counts": portrait_anchor_counts(prompts, cast.get("characters", [])),
    }


def portrait_anchor_counts(prompts: list[dict], characters: list[dict]) -> dict[str, int]:
    """``{slug: plates this portrait will condition}`` (ADR-0028).

    The portrait gate is the last point at which a bad reference is cheap to fix, but it presented
    69 portraits as a flat, unordered grid. Nothing distinguished the one that would anchor 84
    plates from the one that would anchor 7, so the expensive one was approved along with the rest
    and every plate it conditioned inherited its defect.

    Uses P7's own resolver, so the count is exactly the set of plates that will use this portrait —
    a re-implementation that disagreed would be worse than no number at all.
    """
    index = build_cast_index(characters)
    counts: dict[str, int] = {}
    for doc in prompts:
        page_id = str(doc.get("page_id", ""))
        if page_id.startswith(PORTRAIT_PREFIX) or page_id == "cover":
            continue
        depicted = ((doc.get("derived") or {}).get("depicted")) or []
        if not depicted:
            continue
        slug = resolve_character(depicted[0], index)
        if slug:
            counts[slug] = counts.get(slug, 0) + 1
    return counts


@router.put("/books/{book_id}/review/prompt/{page_id}")
def edit_prompt(book_id: str, page_id: str, body: PromptEditBody) -> dict:
    """Persist ``edited_prompt`` and recompute ``final_subject_prompt`` (§4.3, §11.1)."""
    cfg = load_config()
    job = _require(book_id)
    if job.state not in _PORTRAIT_EDIT_STATES:
        raise HTTPException(status_code=409,
                            detail=f"prompts editable only at a review gate (state={job.state})")
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
    if job.state not in _PORTRAIT_EDIT_STATES:
        raise HTTPException(status_code=409,
                            detail=f"cast editable only at a review gate (state={job.state})")
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
    # The description feeds the portrait prompt — re-assemble it so a subsequent regenerate picks up
    # the edit (ADR-0025). No-op if this character has no portrait prompt file (not a major, etc.).
    rederive_portrait_prompt(cfg, job, slug)
    return char


@router.post("/books/{book_id}/approve")
def approve(book_id: str) -> dict:
    """Lock the shot list → ``approved``. Refuses if any renderable plate lacks a prompt (§11.1).

    The approval rules live in :func:`.approve.approve_job` so the auto-approve runner path
    (``AUTO_APPROVE``, ADR-0015) applies the exact same gate; here we just translate its errors
    into HTTP status codes.
    """
    cfg = load_config()
    job = _require(book_id)
    try:
        approve_job(cfg, job)
    except ValueError as exc:  # not in a reviewable state
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ApprovalBlocked as exc:  # a renderable plate has no prompt
        raise HTTPException(
            status_code=422,
            detail={"error": "selected plates missing prompts", "page_ids": exc.page_ids},
        ) from exc
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
    # Apply the same illustration-richness scaling P4 uses, so re-turning the density knob
    # reproduces P4's even-spread placement (one picture per page; expand_choices n=1 is identity).
    n_per_scene = max(1, int((job.bake_config or {}).get("images_per_scene", 1)))
    params = effective_params(PRESETS[body.density_preset], n_per_scene)
    fresh = expand_choices(
        select(_page_scores(book_id), structure, params), _page_texts(book_id), 1
    )

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


@router.post("/books/{book_id}/plates/{page_id}/regen")
async def regen_plate(book_id: str, page_id: str) -> dict:
    """Re-render a single plate with a fresh seed (DESIGN §11.1, §10).

    Two cases, keyed on job state:

    - **Pre-publish** (``rendering``/``rendered``): re-render into the work dir, overwriting the PNG
      + derivatives and bumping the plate's ``render`` provenance in place.
    - **Post-publish** (``published``): the additive ``…-rN.png`` path — render a new variant beside
      the untouched original, bump the bundle ``revision``, and rebuild the manifest (§4.4). Nothing
      already published is mutated.

    A fresh seed is used in both cases so the re-render differs from the original.
    """
    cfg = load_config()
    job = _require(book_id)
    new_seed = secrets.randbelow(2**31)

    if job.state == JobState.PUBLISHED:
        prompt_path = cfg.library_dir / book_id / "prompts" / f"{page_id}.json"
        if not prompt_path.is_file():
            raise HTTPException(status_code=404, detail=f"no published plate {page_id!r}")
        try:
            doc = await regen_published_plate(
                cfg, job, page_id, _imagegen_client(cfg), seed=new_seed
            )
        except GpuUnavailable as exc:
            raise HTTPException(status_code=503, detail=f"imagegen unavailable: {exc}") from exc
        return doc

    # PORTRAITS_REVIEW: the optional portrait gate (ADR-0025) — portraits already rendered, so a
    # single one can be regenerated here before the page plates draw.
    if job.state not in (JobState.PORTRAITS_REVIEW, JobState.RENDERING, JobState.RENDERED):
        raise HTTPException(status_code=409, detail=f"cannot regen from {job.state} (render first)")
    prompt_path = cfg.work_dir / book_id / "prompts" / f"{page_id}.json"
    if not prompt_path.is_file():
        raise HTTPException(status_code=404, detail=f"no prompt for {page_id!r}")
    try:
        await render_plate(cfg, job, page_id, _imagegen_client(cfg), seed=new_seed)
    except GpuUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"imagegen unavailable: {exc}") from exc
    job.save(cfg)
    return _read_json(prompt_path)


@router.get("/books/{book_id}/plate-image/{page_id}.png")
def plate_image(book_id: str, page_id: str) -> FileResponse:
    """Serve a work-dir plate PNG for the post-render / portrait-review views (admin-only).

    Page plates live under ``images/plates/{page_id}.png``; a ``portrait-{slug}`` id maps to
    ``images/portraits/{slug}.png`` (ADR-0025 portrait gate).
    """
    cfg = load_config()
    _require(book_id)
    images = cfg.work_dir / book_id / "images"
    if page_id.startswith(PORTRAIT_PREFIX):
        base = (images / "portraits").resolve()
        target = (base / f"{page_id[len(PORTRAIT_PREFIX):]}.png").resolve()
    else:
        base = (images / "plates").resolve()
        target = (base / f"{page_id}.png").resolve()
    if not target.is_relative_to(base):
        raise HTTPException(status_code=400, detail="bad path")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="no image")
    return FileResponse(target, media_type="image/png")


@router.post("/books/{book_id}/approve-portraits")
def approve_portraits_endpoint(book_id: str) -> dict:
    """Approve the optional portrait gate → advance ``portraits_review → rendering`` (ADR-0025).

    The human has eyeballed / edited / regenerated the portraits; approving lets the page plates
    draw, seeded by the now-approved portrait PNGs.
    """
    cfg = load_config()
    job = _require(book_id)
    try:
        approve_portraits(cfg, job)
    except ValueError as exc:  # not parked at the portrait gate
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return job.to_dict()
