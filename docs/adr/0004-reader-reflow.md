# ADR 0004: Reader reflow — scroll within a logical page

- **Status:** Accepted
- **Date:** 2026-07-13

## Context

The reader must present pages on both phones and desktops. True typographic
screen-pagination (measure/reflow/hyphenate to fill a physical screen) is a deep,
platform-specific rabbit hole, and it complicates plate placement and annotation
anchoring. See DESIGN §13.

## Decision

v1 renders **one logical page as a single vertically-scrolled unit**, with
page-turn navigation between logical pages (swipe / tap-zones on touch, ←/→ and
buttons on desktop). Plates sit at the top of their logical page, full-width, and
open a zoomable lightbox on tap. Chapter-open pages show a chapter title header.

## Consequences

- Scroll-within-page behaves identically on both form factors; plate placement is
  trivial; annotation anchors stay simple (offsets into one page's text).
- We do not get physical-screen pagination in v1; revisit only post-v1 and only
  with evidence it hurts readers.
