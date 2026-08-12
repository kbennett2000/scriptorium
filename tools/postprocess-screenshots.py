#!/usr/bin/env python3
"""Trim dead margins off the captured screenshots and shrink them for the repo.

    python3 tools/postprocess-screenshots.py [--dir docs/assets/screenshots] [--dry-run]

Capture gets the *state* right; this gets the *framing* right. Clipping inside the browser needs a
DOM anchor for every panel, and several of the app's panels scroll internally or sit under a
full-viewport backdrop, so the measured bottom is the viewport rather than the content. Trimming
uniform rows/columns afterwards is layout-independent and needs no per-panel selector.

Two passes:
  1. crop away uniform bottom/right margins, keeping a small even border
  2. quantise to a 256-colour palette — these are flat UI screenshots, so it is visually lossless
     and roughly a 3x saving; PNG stays PNG so nothing else in the docs has to change
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image

MARGIN = 24  # px of breathing room to keep after a trim (in captured 2x pixels)
TOL = 6  # per-channel tolerance when deciding a row/column is uniform


def _trailing_uniform(flags) -> int:
    """How many trailing entries of a boolean 'this line is all background' array are True."""
    n = 0
    for value in reversed(flags.tolist()):
        if not value:
            break
        n += 1
    return n


def trim(im: Image.Image) -> Image.Image:
    """Crop uniform bottom/right margins.

    Every pixel in a line must match the background within TOL. An earlier version averaged a
    sample of pixels per line, which silently ate real content: a row of small buttons averages
    out to near-background, so the annotations panel lost 744px of its width.
    """
    im = im.convert("RGB")
    w, h = im.size
    arr = np.asarray(im, dtype=np.int16)
    ref = arr[h - 1, w - 1]
    is_bg = (np.abs(arr - ref) <= TOL).all(axis=2)  # (h, w) — True where pixel is background

    bottom = _trailing_uniform(is_bg.all(axis=1))
    right = _trailing_uniform(is_bg.all(axis=0))
    new_h = h - max(0, bottom - MARGIN)
    new_w = w - max(0, right - MARGIN)
    if (new_w, new_h) == (w, h):
        return im
    return im.crop((0, 0, max(new_w, 320), max(new_h, 240)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="docs/assets/screenshots")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    total_before = total_after = 0
    for path in sorted(Path(args.dir).glob("*.png")):
        before = path.stat().st_size
        im = Image.open(path)
        size_before = im.size
        out = trim(im)
        quantised = out.quantize(colors=256, method=Image.MEDIANCUT)
        if not args.dry_run:
            quantised.save(path, optimize=True)
        after = path.stat().st_size
        total_before += before
        total_after += after
        note = "" if size_before == out.size else f"  {size_before} -> {out.size}"
        print(f"{path.name:26} {before // 1024:5}KB -> {after // 1024:5}KB{note}")

    print(f"\ntotal {total_before // 1024}KB -> {total_after // 1024}KB")


if __name__ == "__main__":
    main()
