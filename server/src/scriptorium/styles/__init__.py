"""Illustration style catalog loader (DESIGN §9/§10).

The style catalog (``data/styles.json``, schema kind ``styles``) carries the prompt-assembly
strings — ``prefix``/``suffix``/``negative``/``portrait_prefix`` — that turn a subject prompt into
an imagegen request. Style rides in the prompt, not the model. P5 needs it CPU-side to assemble
the cover and portrait pseudo-plate prompts (§10); P7 uses it to wrap page plates.

Like :mod:`scriptorium.schemas`, this resolves the catalog path itself (from the repo root, with a
``SCRIPTORIUM_STYLES`` env override) rather than from a passed ``Config`` — so it works in tests
that point ``Config.shared_dir`` at a tmp dir. The catalog is validated against the ``styles``
schema on first load and cached.
"""

from __future__ import annotations

import json
import os
from functools import cache
from pathlib import Path
from typing import Any

from .. import schemas
from ..bake.phases.base import PipelineBug

# styles/__init__.py -> styles -> scriptorium -> src -> server -> <repo root>
_REPO_ROOT = Path(__file__).resolve().parents[4]


def _catalog_path() -> Path:
    return Path(os.environ.get("SCRIPTORIUM_STYLES", str(_REPO_ROOT / "data" / "styles.json")))


@cache
def load_styles() -> dict[str, Any]:
    """Load, validate, and cache the style catalog (``data/styles.json``)."""
    doc = json.loads(_catalog_path().read_text(encoding="utf-8"))
    schemas.validate("styles", doc)
    return doc


def get_style(style_id: str) -> dict[str, Any]:
    """Return the style with ``id == style_id``.

    An unknown id is a bake-config bug (the admin picker only offers catalog ids), so this
    raises :class:`PipelineBug` — the runner fails the job loudly rather than guessing a style.
    """
    for style in load_styles().get("styles", []):
        if style.get("id") == style_id:
            return style
    raise PipelineBug(f"unknown style_id {style_id!r}")
