"""The reader checkout contract: which bundle files a reader actually downloads.

A published bundle's ``manifest.json`` lists **every** file, including every additive post-publish
``-rN`` image variant (DESIGN §4.4 — plates are never deleted, superseded variants stay on disk as
provenance). The ``reader_required`` globs therefore match *both* an original ``…/0001.webp`` and
its ``…/0001-r2.webp`` regen. Readers must download exactly **one current image per plate**.

Resolution rule (documented convention — there is no current-variant pointer in any schema; the
prompt ``render`` block is ``additionalProperties:false``, NOTES From S10b): **highest ``-rN``
wins.** For each logical image asset (a ``(parent_dir, base_stem, ext)`` group), the current file
is the one with the greatest revision suffix ``-r<N>``; the un-suffixed base is the implicit lowest
(revision 1). Non-image reader-required files (all the ``*.json``) carry no ``-rN`` pattern and
pass through unchanged.

Pure and FastAPI-free so the scripted-client test (and, by mirrored convention, the TS reader) can
import it. The ``GET /api/library`` listing uses :func:`resolved_total_bytes` so the size it reports
is what the reader will actually fetch.
"""

from __future__ import annotations

import re
from typing import Any

# A trailing "-r<digits>" revision suffix on a filename stem (page-ids are 4-digit numerics, so
# "0001-r2" is unambiguous; portrait slugs are kebab words — a slug literally ending "-r<digits>"
# is a theoretical ambiguity we note rather than guard, NOTES From S11).
_VARIANT_RE = re.compile(r"^(?P<stem>.+)-r(?P<n>\d+)$")


def matches_any(rel_path: str, patterns: list[str]) -> bool:
    """Does ``rel_path`` match any glob in the manifest dialect (``/**`` / ``/*`` / exact)?

    Same semantics as ``p8_publish._matches_any`` / ``verify_bundle._matches_any`` (triplication
    noted in NOTES From S11 — a candidate for a shared util).
    """
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


def _variant_key(path: str) -> tuple[tuple[str, str, str], int]:
    """Split ``path`` into a logical-asset group key and its revision number.

    ``images/web/plates/0001-r2.webp`` -> ((``images/web/plates``, ``0001``, ``.webp``), 2).
    ``images/web/plates/0001.webp``    -> ((``images/web/plates``, ``0001``, ``.webp``), 1).
    """
    slash = path.rfind("/")
    parent, name = (path[:slash], path[slash + 1:]) if slash >= 0 else ("", path)
    dot = name.rfind(".")
    stem, ext = (name[:dot], name[dot:]) if dot >= 0 else (name, "")
    m = _VARIANT_RE.match(stem)
    if m:
        return (parent, m.group("stem"), ext), int(m.group("n"))
    return (parent, stem, ext), 1


def resolve_reader_files(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the manifest entries a reader downloads: reader-required, current variant only.

    Expands the ``reader_required`` globs against ``manifest["files"]``, then collapses every
    ``-rN`` image group to its highest revision (base = revision 1). Order follows the manifest's
    file order for determinism.
    """
    required = manifest.get("reader_required", [])
    files = manifest.get("files", [])

    # For each logical-asset group, remember the winning (highest) revision.
    best_rev: dict[tuple[str, str, str], int] = {}
    for entry in files:
        rel = entry["path"]
        if not matches_any(rel, required):
            continue
        group, rev = _variant_key(rel)
        if rev > best_rev.get(group, -1):
            best_rev[group] = rev

    resolved: list[dict[str, Any]] = []
    for entry in files:
        rel = entry["path"]
        if not matches_any(rel, required):
            continue
        group, rev = _variant_key(rel)
        if best_rev.get(group) == rev:
            resolved.append(entry)
    return resolved


def resolved_total_bytes(manifest: dict[str, Any]) -> int:
    """Total bytes a reader downloads for this bundle (the resolved reader-required set)."""
    return sum(int(e["bytes"]) for e in resolve_reader_files(manifest))
