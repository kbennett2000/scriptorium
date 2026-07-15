"""Style catalog sanity (data/styles.json, ADR-0013).

Guards the shipped catalog: schema-valid (via load_styles), unique ids, and every `imagegen_style`
is either null (prompt-only) or one of imagegen-service's known preset names — a typo there would
silently fall back to prompt-only rendering (the service ignores unknown style names).
"""

from __future__ import annotations

from scriptorium.styles import load_styles

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
