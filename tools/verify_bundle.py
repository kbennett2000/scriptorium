#!/usr/bin/env python3
"""Standalone validator for a published scriptorium bundle (DESIGN §4.2–4.4).

Checks a ``library/{id}`` (or the committed fixture bundle) is internally consistent and
reader-serviceable:

1. **Manifest ↔ disk** — every ``manifest.files`` entry exists with a matching sha256 + byte count,
   and no bundle file is missing from the manifest (``manifest.json`` and ``*.src.sha256`` sidecars
   excepted).
2. **Schemas** — ``meta``, ``structure``, ``cast``, ``selection``, ``manifest``, every ``pages/*``
   and every ``prompts/*`` validates against the normative ``shared/schemas`` (schema/shape only —
   never value equality; the fixtures deliberately diverge, see NOTES From S7/S8).
3. **reader_required** — every glob resolves to at least one present file.
4. **Cross-references** — selection plate ids exist as pages; each non-retired page plate has its
   prompt + native/web/thumb image trio; ``cover`` and each portrait have a prompt + image trio;
   retired plates keep their files (additive invariant); post-publish ``-rN`` variants tolerated.

Importable — ``verify_bundle(path) -> list[str]`` returns the errors (empty ⇒ valid) — and runnable:
``uv run python ../tools/verify_bundle.py <bundle_dir>`` exits nonzero on any failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
# Make the server package importable even when run outside its installed env.
sys.path.insert(0, str(_REPO_ROOT / "server" / "src"))

from scriptorium import schemas  # noqa: E402

_SIDECAR_SUFFIX = ".src.sha256"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _matches_any(rel_path: str, patterns: list[str]) -> bool:
    for pat in patterns:
        if pat.endswith("/**"):
            if rel_path.startswith(pat[:-2]):
                return True
        elif pat.endswith("/*"):
            prefix = pat[:-1]
            if rel_path.startswith(prefix) and "/" not in rel_path[len(prefix):]:
                return True
        elif rel_path == pat:
            return True
    return False


def _check_manifest_vs_disk(bundle: Path, manifest: dict, errors: list[str]) -> None:
    listed = {f["path"] for f in manifest.get("files", [])}
    for entry in manifest.get("files", []):
        rel = entry["path"]
        path = bundle / rel
        if not path.is_file():
            errors.append(f"manifest lists missing file: {rel}")
            continue
        actual = _sha256(path)
        if actual != entry["sha256"]:
            errors.append(f"sha256 mismatch: {rel} (manifest {entry['sha256'][:12]}…, "
                          f"disk {actual[:12]}…)")
        if path.stat().st_size != entry["bytes"]:
            errors.append(f"byte-count mismatch: {rel}")
    # Every real bundle file must be listed (except the manifest itself + sidecars).
    for path in sorted(bundle.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(bundle).as_posix()
        if rel == "manifest.json" or path.name.endswith(_SIDECAR_SUFFIX):
            continue
        if rel not in listed:
            errors.append(f"bundle file not in manifest: {rel}")


def _check_schemas(bundle: Path, errors: list[str]) -> None:
    singles = {
        "meta": "meta.json", "structure": "structure.json",
        "cast": "cast.json", "selection": "selection.json", "manifest": "manifest.json",
    }
    for kind, name in singles.items():
        path = bundle / name
        if not path.is_file():
            errors.append(f"missing {name}")
            continue
        try:
            schemas.validate(kind, _load(path))
        except Exception as exc:  # jsonschema.ValidationError et al.
            errors.append(f"{name} fails {kind} schema: {exc}")
    for kind, sub in (("page", "pages"), ("prompt", "prompts")):
        for path in sorted((bundle / sub).glob("*.json")):
            try:
                schemas.validate(kind, _load(path))
            except Exception as exc:
                errors.append(f"{sub}/{path.name} fails {kind} schema: {exc}")


def _check_reader_required(bundle: Path, manifest: dict, errors: list[str]) -> None:
    present = [p.relative_to(bundle).as_posix() for p in bundle.rglob("*") if p.is_file()]
    for glob in manifest.get("reader_required", []):
        if not any(_matches_any(rel, [glob]) for rel in present):
            errors.append(f"reader_required glob matches no file: {glob}")


def _image_trio_ok(bundle: Path, native: str, web: str, thumb: str) -> bool:
    """A plate is present if its native PNG or a ``-rN`` variant exists, with web + thumb peers."""
    def _exists(rel: str) -> bool:
        p = bundle / rel
        if p.is_file():
            return True
        # tolerate additive post-publish variants (e.g. 0007-r2.png)
        parent, stem, suffix = p.parent, p.stem, p.suffix
        return any(parent.glob(f"{stem}-r*{suffix}"))
    return _exists(native) and _exists(web) and _exists(thumb)


def _check_cross_refs(bundle: Path, errors: list[str]) -> None:
    try:
        selection = _load(bundle / "selection.json")
        cast = _load(bundle / "cast.json")
    except Exception as exc:
        errors.append(f"cannot read selection/cast for cross-refs: {exc}")
        return
    page_ids = {p.stem for p in (bundle / "pages").glob("*.json")}

    for plate in selection.get("plates", []):
        pid = plate["page_id"]
        if pid not in page_ids:
            errors.append(f"selection plate {pid} has no page file")
        # Both selected/rendered and retired plates keep their files (additive invariant, §4.4).
        if not (bundle / "prompts" / f"{pid}.json").is_file():
            errors.append(f"plate {pid} missing prompt file")
        if not _image_trio_ok(bundle, f"images/plates/{pid}.png",
                              f"images/web/plates/{pid}.webp", f"images/thumbs/plates/{pid}.webp"):
            errors.append(f"plate {pid} (status={plate.get('status')}) missing image trio")

    # Cover pseudo-plate (always) + portraits for majors with a portrait path.
    if (bundle / "prompts" / "cover.json").is_file():
        if not _image_trio_ok(bundle, "images/cover.png", "images/web/cover.webp",
                              "images/thumbs/cover.webp"):
            errors.append("cover missing image trio")
    else:
        errors.append("missing cover prompt")

    for char in cast.get("characters", []):
        if not char.get("portrait"):
            continue
        slug = char["slug"]
        if not (bundle / "prompts" / f"portrait-{slug}.json").is_file():
            errors.append(f"portrait-{slug} missing prompt file")
        if not _image_trio_ok(bundle, f"images/portraits/{slug}.png",
                              f"images/web/portraits/{slug}.webp",
                              f"images/thumbs/portraits/{slug}.webp"):
            errors.append(f"portrait-{slug} missing image trio")


def verify_bundle(bundle_dir: Path | str) -> list[str]:
    """Return a list of problems with the bundle at ``bundle_dir`` (empty ⇒ valid)."""
    bundle = Path(bundle_dir)
    errors: list[str] = []
    if not bundle.is_dir():
        return [f"not a directory: {bundle}"]
    manifest_path = bundle / "manifest.json"
    if not manifest_path.is_file():
        return [f"missing manifest.json in {bundle}"]
    try:
        manifest = _load(manifest_path)
    except Exception as exc:
        return [f"manifest.json is not valid JSON: {exc}"]

    _check_manifest_vs_disk(bundle, manifest, errors)
    _check_schemas(bundle, errors)
    _check_reader_required(bundle, manifest, errors)
    _check_cross_refs(bundle, errors)
    return errors


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate a published scriptorium bundle.")
    ap.add_argument("bundle", type=Path, help="path to the bundle directory (library/{id})")
    args = ap.parse_args()
    errors = verify_bundle(args.bundle)
    if errors:
        print(f"FAIL — {len(errors)} problem(s) in {args.bundle}:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    print(f"OK — {args.bundle} is a valid bundle.")


if __name__ == "__main__":
    main()
