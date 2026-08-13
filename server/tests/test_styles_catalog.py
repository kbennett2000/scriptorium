"""Style catalog sanity (data/styles.json, ADR-0013).

Guards the shipped catalog: schema-valid (via load_styles), unique ids, and every `imagegen_style`
is either null (prompt-only) or one of imagegen-service's known preset names — a typo there would
silently fall back to prompt-only rendering (the service ignores unknown style names).
"""

from __future__ import annotations

import pytest

from scriptorium.bake.phases.base import PipelineBug
from scriptorium.styles import CUSTOM_STYLE_ID, load_styles, resolve_style

# imagegen-service's LoRA-backed preset names (its GET /styles catalog, ADR-0011/0012). A style's
# `imagegen_style` must match one of these exactly to apply the LoRA; anything else renders
# prompt-only. Kept here as the single documented expectation for the shipped catalog.
_KNOWN_IMAGEGEN_STYLES = {
    "pixel art", "oil painting", "comic book", "lego-style", "pencil sketch", "watercolour",
    "anime", "storybook", "3d", "cyberpunk", "ukiyo-e", "claymation",
}


def test_catalog_loads_and_is_schema_valid() -> None:
    styles = load_styles()["styles"]
    assert len(styles) >= 4


def test_ids_are_unique() -> None:
    ids = [s["id"] for s in load_styles()["styles"]]
    assert len(ids) == len(set(ids)), ids


def test_imagegen_style_is_null_or_a_known_preset() -> None:
    for s in load_styles()["styles"]:
        val = s["imagegen_style"]
        assert val is None or val in _KNOWN_IMAGEGEN_STYLES, f"{s['id']}: {val!r}"


def test_original_prompt_only_styles_stay_null() -> None:
    # Immutability guard: the four pre-ADR-0013 styles must remain prompt-only (imagegen_style null)
    # so already-published books (e.g. The Time Machine on `engraving`) are unaffected.
    by_id = {s["id"]: s for s in load_styles()["styles"]}
    for sid in ("engraving", "woodcut", "watercolor", "gouache-storybook"):
        assert by_id[sid]["imagegen_style"] is None


# --- No-style + custom-style resolution (ADR-0031) --------------------------


def test_no_style_is_a_prompt_only_catalog_entry() -> None:
    # "No style" is a real catalog entry with empty prompt strings + null LoRA, so the subject goes
    # to the model raw.
    none = {s["id"]: s for s in load_styles()["styles"]}["none"]
    assert none["imagegen_style"] is None
    assert none["prefix"] == "" and none["suffix"] == "" and none["portrait_prefix"] == ""


def test_resolve_style_custom_builds_prompt_only_prefix() -> None:
    style = resolve_style({"style_id": CUSTOM_STYLE_ID, "custom_style": "photorealistic"})
    assert style["imagegen_style"] is None  # custom never applies a LoRA
    assert style["prefix"] == "photorealistic, "
    assert style["portrait_prefix"] == "photorealistic, "


def test_resolve_style_custom_empty_is_pure_subject() -> None:
    # Empty custom text ⇒ no prefix, identical to the "No style" entry.
    style = resolve_style({"style_id": CUSTOM_STYLE_ID, "custom_style": "  "})
    assert style["prefix"] == "" and style["suffix"] == ""


def test_resolve_style_catalog_id_passes_through() -> None:
    assert resolve_style({"style_id": "engraving"})["id"] == "engraving"


def test_resolve_style_unknown_id_still_raises() -> None:
    with pytest.raises(PipelineBug):
        resolve_style({"style_id": "no-such-style"})
