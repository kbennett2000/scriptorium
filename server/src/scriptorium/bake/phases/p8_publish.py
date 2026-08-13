"""P8 — publish: assemble the immutable library bundle (DESIGN §4.2–4.4, §7.1).

The last mile of the bakery. A single CPU rest→rest phase (``rendered → published``, like P4 — no
enter step): it copies the render-ready ``work/{id}`` tree into ``library/{id}``, builds
``meta.json`` (identity + pinned bake provenance) and ``manifest.json`` (per-file sha256 +
``reader_required`` globs, §4.3), and enforces the **publish integrity guard** (§4.4 — once a bundle
is published every ``pages/*.json`` is frozen byte-for-byte; a re-publish whose page bytes differ is
refused, which is what makes annotation anchors permanently safe).

Revisions are **additive** (§4.4): re-publishing bumps ``revision`` and may add files / update
``selection.json``/``prompts/*``/``meta.stats``, but never rewrites a published page or deletes a
plate. :func:`regen_published_plate` implements the post-publish per-plate regen: it renders a new
``…/{page}-rN.png`` (N = the new revision) beside the untouched original, updates the plate's
``render`` provenance, bumps the revision, and rebuilds the manifest in place — no full re-publish.

Everything is offline-safe: ``meta.bake`` pinning (transform versions, model tags, ``git describe``)
is **best-effort** and degrades to non-empty placeholders when the GPU services are unreachable, so
the whole phase runs GPU-less in tests. Per CLAUDE.md nothing here asserts model/image *content*.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from ... import schemas
from ...render.imagegen import ImagegenClient
from ...styles import get_style
from ..job import Job, JobState
from .base import PipelineBug, Unit
from .p7_render import (
    _asset_spec,
    _now_iso,
    portrait_reference,
    reference_conditioning,
    render_to_spec,
)

# The §4.3 reader-required globs, verbatim (readers download only these by default; full-res
# archival ``images/plates/*.png`` etc. are excluded).
READER_REQUIRED: tuple[str, ...] = (
    "meta.json", "structure.json", "pages/*", "cast.json", "selection.json",
    "images/web/**", "images/thumbs/**",
)

# Work-tree artifacts that must never enter a published bundle: the WebP idempotency sidecars, the
# raw scene ledgers (their merged form already rides on ``pages/*``), and the archived source.
_SIDECAR_SUFFIX = ".src.sha256"
_QUICK_TIMEOUT_S = 5.0


# --- paths / io -------------------------------------------------------------


def _library_dir(cfg: Any, job: Job) -> Path:
    return cfg.library_dir / job.book_id


def _work_dir(cfg: Any, job: Job) -> Path:
    return cfg.work_dir / job.book_id


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _suffix_path(path: Path, suffix: str) -> Path:
    """Insert ``suffix`` before the extension: ``plates/0007.png`` + ``-r2`` → ``0007-r2.png``."""
    return path.with_name(f"{path.stem}{suffix}{path.suffix}")


# --- manifest (DESIGN §4.3) -------------------------------------------------


def _matches_any(rel_path: str, patterns: tuple[str, ...]) -> bool:
    """Match a bundle-relative POSIX path against the ``reader_required`` glob dialect."""
    for pat in patterns:
        if pat.endswith("/**"):
            if rel_path.startswith(pat[:-2]):  # keep trailing '/'
                return True
        elif pat.endswith("/*"):
            prefix = pat[:-1]  # keep trailing '/'
            if rel_path.startswith(prefix) and "/" not in rel_path[len(prefix):]:
                return True
        elif rel_path == pat:
            return True
    return False


def build_manifest(bundle_dir: Path, book_id: str, revision: int) -> dict:
    """The §4.3 manifest for ``bundle_dir``: every file's sha256 + bytes, ``reader_required`` globs.

    Excludes ``manifest.json`` itself (it can't hash the file being written) and any
    ``*.src.sha256`` idempotency sidecars (a work-tree artifact that must never leak into a bundle).
    """
    files = []
    for path in sorted(bundle_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(bundle_dir).as_posix()
        if rel == "manifest.json" or path.name.endswith(_SIDECAR_SUFFIX):
            continue
        files.append({"path": rel, "sha256": _sha256(path), "bytes": path.stat().st_size})
    total_reader = sum(f["bytes"] for f in files if _matches_any(f["path"], READER_REQUIRED))
    doc = {
        "book_id": book_id, "revision": revision, "bundle_version": 1,
        "content_fingerprint": _content_fingerprint(files),
        "files": files, "reader_required": list(READER_REQUIRED),
        "total_bytes_reader": total_reader,
    }
    schemas.validate("manifest", doc)
    return doc


def _content_fingerprint(files: list[dict]) -> str:
    """A single SHA-256 identity for the bundle content: hash of the sorted ``path\\0sha256`` list.

    Derived purely from the file list, so it differs whenever any file's bytes change — even when
    ``book_id`` and ``revision`` collide (a delete + re-make restarts revision at 1). Lets a reader
    detect a changed bundle by comparing one field instead of diffing every file.
    """
    lines = sorted(f"{f['path']}\0{f['sha256']}" for f in files)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


# --- meta.json (DESIGN §4.3, ADR-0003) --------------------------------------


def _get_json(url: str) -> Any | None:
    """Best-effort GET returning parsed JSON, or ``None`` on any failure (offline-safe)."""
    try:
        with httpx.Client(timeout=_QUICK_TIMEOUT_S) as client:
            resp = client.get(url)
        if resp.is_success:
            return resp.json()
    except Exception:
        return None
    return None


def _git_describe() -> str:
    """``git describe`` for pipeline provenance; ``"unknown"`` off a git tree / on failure."""
    try:
        out = subprocess.run(  # noqa: S603,S607
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=Path(__file__).resolve().parent, capture_output=True, text=True, check=False,
        )
        described = out.stdout.strip()
        return described or "unknown"
    except Exception:
        return "unknown"


def _pin_bake(cfg: Any) -> dict:
    """Pin the bake provenance block (§4.3). Best-effort + offline-safe (non-empty placeholders).

    Transform versions and model tags are queried from the GPU services when reachable and fall back
    to ``"unknown"`` / an empty map when not; ``pipeline_version`` is ``git describe``. The meta
    schema requires non-empty ``models.*`` and ``pipeline_version``, so every fallback is non-empty.
    """
    url_host = urlsplit(cfg.tts_url).netloc if cfg.tts_url else "offline"

    transforms: dict[str, str] = {}
    if cfg.tts_url:
        payload = _get_json(cfg.tts_url.rstrip("/") + "/v1/transforms")
        if isinstance(payload, dict):
            raw = payload.get("transforms", payload)
            if isinstance(raw, dict):
                transforms = {str(k): str(v) for k, v in raw.items()}

    llm = "unknown"
    if cfg.tts_url:
        health = _get_json(cfg.tts_url.rstrip("/") + "/health")
        if isinstance(health, dict):
            llm = str(health.get("model") or health.get("llm") or "unknown")

    imagegen = "unknown"
    if getattr(cfg, "imagegen_url", None):
        health = _get_json(cfg.imagegen_url.rstrip("/") + "/health")
        if isinstance(health, dict):
            imagegen = str(health.get("model") or health.get("checkpoint") or "unknown")

    return {
        "completed_at": _now_iso(),
        "transform_service": {"url_host": url_host or "offline", "transforms": transforms},
        "models": {"llm": llm or "unknown", "imagegen": imagegen or "unknown"},
        "pipeline_version": _git_describe(),
    }


def _source_block(job: Job) -> dict:
    """The §4.3 ``meta.source`` block. Maps the admin API kind → the stored ``gutenberg|user``."""
    src = job.source or {}
    kind = "gutenberg" if src.get("kind") == "gutenberg" else "user"
    block: dict[str, Any] = {"kind": kind, "retrieved_at": job.created_at}
    if kind == "gutenberg" and src.get("gutenberg_id"):
        block["gutenberg_id"] = int(src["gutenberg_id"])
    return block


def build_meta(cfg: Any, job: Job, bundle_dir: Path, revision: int) -> dict:
    """Assemble a schema-valid ``meta.json`` from the job config + the assembled bundle + pins."""
    cfgd = job.bake_config or {}
    src = job.source or {}
    structure = _read_json(bundle_dir / "structure.json")
    pages = [_read_json(p) for p in sorted((bundle_dir / "pages").glob("*.json"))]
    selection = _read_json(bundle_dir / "selection.json")
    plates = [p for p in selection.get("plates", []) if p.get("status") != "retired"]

    meta = {
        "bundle_version": 1,
        "book_id": job.book_id,
        "revision": revision,
        "title": cfgd.get("title") or job.title or src.get("title") or job.book_id,
        "author": cfgd.get("author") or src.get("author") or "",
        "language": src.get("language") or "en",
        "source": _source_block(job),
        "era": cfgd.get("era") or "unspecified",
        "style_id": cfgd["style_id"],
        "density_preset": cfgd.get("density_preset", "classic"),
        "images_per_scene": int(cfgd.get("images_per_scene", 1)),
        "portraits_enabled": bool(cfgd.get("portraits_enabled", True)),
        "bake": _pin_bake(cfg),
        "stats": {
            "pages": len(pages),
            "words": sum(int(p.get("word_count", 0)) for p in pages),
            "plates": len(plates),
            "chapters": len(structure.get("chapters", [])),
        },
    }
    # Pin the *chosen* base model (ADR-0030) as the imagegen provenance tag, overriding the
    # service-reported default, so re-renders (-rN, re-rolls) reproduce this book's model.
    if cfgd.get("model"):
        meta["bake"]["models"]["imagegen"] = str(cfgd["model"])
    schemas.validate("meta", meta)
    return meta


# --- assembly + integrity guard (DESIGN §4.4) -------------------------------


def _integrity_guard(work: Path, library: Path) -> None:
    """Refuse to re-publish if any already-published ``pages/*.json`` would change (§4.4).

    Published page text is frozen forever (annotation anchors depend on it). Every page already in
    the library must exist in the new bake and be byte-identical, else the publish is refused.
    """
    lib_pages = library / "pages"
    if not lib_pages.is_dir():
        return  # first publish — nothing frozen yet
    work_pages = work / "pages"
    for published in sorted(lib_pages.glob("*.json")):
        candidate = work_pages / published.name
        if not candidate.is_file() or candidate.read_bytes() != published.read_bytes():
            raise PipelineBug(
                f"publish integrity violation: pages/{published.name} differs from the "
                "already-published bundle (published page text is frozen, §4.4)"
            )


def _copy_bundle_files(work: Path, library: Path) -> None:
    """Copy the §4.2 bundle files from the work tree into the library (additive; never deletes).

    Copies ``structure.json``/``cast.json``/``selection.json``, ``pages/*``, ``prompts/*``, and
    ``images/**`` — **excluding** ``*.src.sha256`` sidecars, the raw ``ledgers/``, and the archived
    source. Existing library files (e.g. post-publish ``-rN`` variants) are left in place.
    """
    for name in ("structure.json", "cast.json", "selection.json"):
        src = work / name
        if src.is_file():
            _write_bytes(library / name, src.read_bytes())
    for sub in ("pages", "prompts"):
        for src in sorted((work / sub).glob("*.json")):
            _write_bytes(library / sub / src.name, src.read_bytes())
    images = work / "images"
    for src in sorted(images.rglob("*")):
        if not src.is_file() or src.name.endswith(_SIDECAR_SUFFIX):
            continue
        _write_bytes(library / "images" / src.relative_to(images), src.read_bytes())


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def publish_bundle(cfg: Any, job: Job) -> dict:
    """Assemble ``library/{id}`` from ``work/{id}``: guard → copy → meta → manifest. Idempotent.

    Returns the manifest. Raises :class:`PipelineBug` if the integrity guard refuses the re-publish.
    """
    work = _work_dir(cfg, job)
    library = _library_dir(cfg, job)

    _integrity_guard(work, library)

    # Revision: bump past the existing published revision, else start at 1.
    prev_meta = library / "meta.json"
    revision = (_read_json(prev_meta)["revision"] + 1) if prev_meta.is_file() else 1

    library.mkdir(parents=True, exist_ok=True)
    _copy_bundle_files(work, library)
    _write_json(library / "meta.json", build_meta(cfg, job, library, revision))
    manifest = build_manifest(library, job.book_id, revision)
    _write_json(library / "manifest.json", manifest)
    return manifest


# --- post-publish per-plate regen (DESIGN §4.4, §10) ------------------------


async def regen_published_plate(
    cfg: Any, job: Job, page_id: str, client: ImagegenClient, *, seed: int
) -> dict:
    """Additively re-render one published plate as a ``-rN`` variant and bump the revision (§10).

    Renders new pixels into ``library/{id}/…/{page_id}-rN.png`` (+ web/thumb) beside the untouched
    original, updates the plate's ``prompts/{page_id}.json`` ``render`` provenance, bumps
    ``meta.revision``, and rebuilds the manifest in place. Nothing published is mutated (§4.4), so
    the integrity guard is never at risk. Returns the updated prompt doc.
    """
    library = _library_dir(cfg, job)
    prompt_path = library / "prompts" / f"{page_id}.json"
    doc = _read_json(prompt_path)
    meta_path = library / "meta.json"
    meta = _read_json(meta_path)
    new_rev = int(meta["revision"]) + 1

    # The rendered strings were pinned at publish; a regen re-fires the same prompt with a new seed.
    wrapped = doc.get("wrapped_prompt", doc["final_subject_prompt"])
    negative = doc.get("negative_prompt", "")
    imagegen_style = get_style(meta["style_id"]).get("imagegen_style")
    base = _asset_spec(library, page_id)
    suffix = f"-r{new_rev}"
    spec = replace(
        base,
        src=_suffix_path(base.src, suffix),
        web=_suffix_path(base.web, suffix),
        thumb=_suffix_path(base.thumb, suffix),
    )
    # Re-condition on the same character portrait the original render used (ADR-0023/0026).
    # Without this a regen silently drops the identity anchor, so the one plate you asked to be
    # redrawn comes back with a different-looking character than every other page.
    cast_path = library / "cast.json"
    characters = (_read_json(cast_path) or {}).get("characters", []) if cast_path.is_file() else []
    references, reference_slug = portrait_reference(
        ((doc.get("derived") or {}).get("depicted")) or [],
        characters,
        library / "images" / "portraits",
    )
    strength, start = reference_conditioning(((doc.get("derived") or {}).get("depicted")) or [])
    await render_to_spec(
        client,
        wrapped,
        negative,
        spec,
        seed,
        imagegen_style,
        references=references,
        reference_strength=strength,
        reference_start=start,
    )

    doc["render"] = {
        "at": _now_iso(),
        "params_echo": {"seed": seed, "width": spec.width, "height": spec.height},
        "attempts": int((doc.get("render") or {}).get("attempts", 0)) + 1,
        "reference_slug": reference_slug,
    }
    schemas.validate("prompt", doc)
    _write_json(prompt_path, doc)

    meta["revision"] = new_rev
    meta["bake"] = _pin_bake(cfg)
    schemas.validate("meta", meta)
    _write_json(meta_path, meta)

    _write_json(library / "manifest.json", build_manifest(library, job.book_id, new_rev))
    return doc


# --- phase ------------------------------------------------------------------


class Publish:
    """P8: assemble the immutable library bundle (``rendered → published``)."""

    name = "p8_publish"
    from_state = JobState.RENDERED
    to_state = JobState.PUBLISHED
    is_gpu = False

    def units(self, job: Job, cfg: Any) -> list[Unit]:
        return [Unit(id="__publish__")]

    def unit_done(self, job: Job, cfg: Any, unit: Unit) -> bool:
        # Idempotent single-unit assembly; always re-run so a killed publish resumes cleanly.
        return False

    def run_unit(self, job: Job, cfg: Any, unit: Unit) -> None:
        publish_bundle(cfg, job)
