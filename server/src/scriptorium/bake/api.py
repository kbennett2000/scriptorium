"""Admin API for books & jobs (DESIGN §11.1, the four S4 endpoint groups).

``POST /api/admin/books`` runs **P0 inline** — ingest → paginate → archive source →
persist ``work/{id}/pages/*`` + ``structure.json`` (the paginator validates both against
their schemas) — and creates the job at state ``ingested``. The remaining endpoints list/
inspect books, edit chapter breaks pre-P1 (409 once past P0), and control the job
(start/pause/resume). Post-P0 phases are driven by the background runner (§11.2); no real
phase is registered yet (S5 adds P1), so a started job simply rests at ``ingested``.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import Config, load_config
from ..gpu_probe import probe_gpu
from ..ingest import base as ingest
from ..ingest.base import (
    Chapter,
    RawBook,
    SourceSpec,
    archive_source,
    read_source,
)
from ..library.purge import purge_book
from ..paginate import PaginatedBook, paginate
from . import job as jobmod
from .job import GPU_STATES, Job, JobState
from .progress import status_extras

router = APIRouter(prefix="/api/admin")


# --- request bodies ---------------------------------------------------------


class SourceBody(BaseModel):
    kind: str
    gutenberg_id: int | None = None
    path: str | None = None
    text: str | None = None
    filename: str | None = None
    title: str | None = None
    author: str | None = None
    language: str | None = None

    def to_spec(self) -> SourceSpec:
        return SourceSpec(
            kind=self.kind,
            gutenberg_id=self.gutenberg_id,
            path=Path(self.path) if self.path else None,
            text=self.text,
            filename=self.filename,
            title=self.title,
            author=self.author,
            language=self.language,
        )


class BakeBody(BaseModel):
    style_id: str
    density_preset: str = "classic"
    images_per_scene: int = Field(default=1, ge=1)
    era: str | None = None
    portraits_enabled: bool = True
    # Optional portrait-review gate (ADR-0025): when true, the bake pauses at ``portraits_review``
    # after the portraits render so a human can eyeball / edit / regenerate each one before the rest
    # of the book draws. Overrides unattended AUTO_APPROVE for that single stop. Off by default.
    portrait_review: bool = False
    title: str | None = None
    author: str | None = None


class CreateBookBody(BaseModel):
    source: SourceBody
    bake: BakeBody


class ChapterBody(BaseModel):
    title: str | None = None
    paragraphs: list[str]


class ChaptersEditBody(BaseModel):
    chapters: list[ChapterBody]


# --- P0 helpers -------------------------------------------------------------


def _persist_pagination(cfg: Config, book_id: str, book: PaginatedBook) -> None:
    """Write pages + structure under ``work/{book_id}/``, replacing any prior run.

    Stale page files from a previous pagination (e.g. a chapter-break edit that reduces
    the page count) are removed first so ``work/`` reflects exactly the current output.
    """
    work = cfg.work_dir / book_id
    pages_dir = work / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    for stale in pages_dir.glob("*.json"):
        stale.unlink()
    for page in book.pages:
        (pages_dir / f"{page['id']}.json").write_text(
            json.dumps(page, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    (work / "structure.json").write_text(
        json.dumps(book.structure, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run_p0(cfg: Config, body: CreateBookBody) -> Job:
    """Ingest + paginate + archive + persist, returning a saved job at ``ingested``."""
    spec = body.source.to_spec()
    raw = ingest.load(spec)
    book_id = raw.book_id

    # Archive the raw source for provenance (§5.1). User sources expose their bytes via
    # read_source; a gutenberg source is adapter-fetched and archived elsewhere (not S4).
    try:
        text, filename = read_source(spec)
        archive_source(cfg.work_dir, book_id, filename, text.encode("utf-8"))
    except ValueError:
        pass

    _persist_pagination(cfg, book_id, paginate(raw))

    job = Job(
        id=book_id,
        book_id=book_id,
        state=JobState.CREATED,
        source=body.source.model_dump(),
        bake_config=body.bake.model_dump(),
        title=raw.title,
        warnings=list(raw.warnings),
    )
    job.transition(JobState.INGESTED)
    # Unattended mode (ADR-0020): mark the freshly-ingested job started so the runner advances it
    # without a Start click. Off by default (keeps the pre-P1 chapter-edit window).
    if cfg.auto_start:
        job.started = True
    job.save(cfg)
    return job


# --- endpoints --------------------------------------------------------------


@router.post("/books")
def create_book(body: CreateBookBody) -> dict:
    cfg = load_config()
    try:
        job = run_p0(cfg, body)
    except ValueError as exc:  # unknown kind / bad source
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"book_id": job.book_id, "state": job.state, "warnings": job.warnings}


@router.get("/gpu")
def gpu_status() -> dict:
    """Best-effort GPU/CPU status for the admin UI's live indicator (never 500s; see gpu_probe)."""
    return probe_gpu()


@router.get("/books")
def list_books() -> dict:
    cfg = load_config()
    return {"books": [j.to_dict() for j in jobmod.list_jobs(cfg)]}


@router.get("/books/{book_id}")
def get_book(book_id: str) -> dict:
    cfg = load_config()
    job = jobmod.load(cfg, book_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"no such book {book_id!r}")
    # Additive: the raw job record plus read-time progress + liveness for the admin poll.
    return {**job.to_dict(), **status_extras(job, cfg)}


@router.delete("/books/{book_id}")
def delete_book(book_id: str) -> dict:
    """Permanently delete a book and EVERYTHING it owns (bundle, work, jobs, every profile's picture
    sets + sync data). Owner-initiated + irreversible. Refuses while the book is rendering."""
    cfg = load_config()
    job = jobmod.load(cfg, book_id)
    if job is None and not (cfg.library_dir / book_id).is_dir():
        raise HTTPException(status_code=404, detail=f"no such book {book_id!r}")
    if job is not None and job.state in GPU_STATES:
        raise HTTPException(
            status_code=409, detail=f"book is busy ({job.state}); try again once it settles"
        )
    try:
        removed = purge_book(cfg, book_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"deleted": book_id, "removed": removed}


@router.put("/books/{book_id}/chapters")
def edit_chapters(book_id: str, body: ChaptersEditBody) -> dict:
    cfg = load_config()
    job = _require(book_id)
    if job.state != JobState.INGESTED:
        raise HTTPException(
            status_code=409,
            detail=f"chapter breaks are editable only pre-P1 (state={job.state})",
        )
    raw = RawBook(
        book_id=job.book_id,
        source_kind=ingest.SOURCE_USER,
        chapters=[Chapter(title=c.title, paragraphs=c.paragraphs) for c in body.chapters],
        title=job.title,
    )
    _persist_pagination(cfg, job.book_id, paginate(raw))
    job.save(cfg)  # touch updated_at; state stays ingested
    return job.to_dict()


@router.post("/jobs/{book_id}/start")
def start_job(book_id: str) -> dict:
    cfg = load_config()
    job = _require(book_id)
    job.started = True
    job.save(cfg)
    return job.to_dict()


@router.post("/jobs/{book_id}/pause")
def pause_job(book_id: str) -> dict:
    cfg = load_config()
    job = _require(book_id)
    if job.state in (JobState.PAUSED, JobState.FAILED, JobState.PUBLISHED):
        raise HTTPException(status_code=409, detail=f"cannot pause state={job.state}")
    job.transition(JobState.PAUSED)
    job.save(cfg)
    return job.to_dict()


@router.post("/jobs/{book_id}/resume")
def resume_job(book_id: str) -> dict:
    cfg = load_config()
    job = _require(book_id)
    if job.state != JobState.PAUSED:
        raise HTTPException(status_code=409, detail=f"cannot resume state={job.state}")
    job.transition(job.prev_state or JobState.INGESTED)
    job.save(cfg)
    return job.to_dict()


def _require(book_id: str) -> Job:
    job = jobmod.load(load_config(), book_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"no such book {book_id!r}")
    return job
