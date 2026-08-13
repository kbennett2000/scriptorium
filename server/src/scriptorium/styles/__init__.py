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


# The sentinel style id (ADR-0031) for "use the owner's free-text look" — not a catalog entry, so
# the bake carries the text in ``bake_config['custom_style']`` and :func:`resolve_style` synthesises
# the style dict. ("No style" is a real catalog entry with empty prefix/suffix, so it needs nothing
# special here.)
CUSTOM_STYLE_ID = "custom"


def resolve_style(bake_config: dict[str, Any]) -> dict[str, Any]:
    """Materialise the style dict for a bake/art-set (ADR-0031).

    For the ``custom`` sentinel, build a synthetic prompt-only style from the free-text
    ``custom_style`` (e.g. "photorealistic") — no LoRA, the text as the prefix so it leads the
    wrapped prompt, empty text ⇒ pure subject (identical to the "No style" catalog entry). Every
    other id resolves through :func:`get_style`.
    """
    style_id = bake_config.get("style_id")
    if style_id == CUSTOM_STYLE_ID:
        text = (bake_config.get("custom_style") or "").strip()
        prefix = f"{text}, " if text else ""
        return {
            "id": CUSTOM_STYLE_ID,
            "name": "Custom",
            "consistency_friendly": False,
            "imagegen_style": None,
            "prefix": prefix,
            "suffix": "",
            "negative": "",
            "portrait_prefix": prefix,
            "params": {"steps": None, "cfg": None},
        }
    return get_style(style_id)
