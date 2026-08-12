# Screenshots

Every screenshot in the docs is **real** — captured from a live stack against a baked copy of
*The Strange Case of Dr. Jekyll and Mr. Hyde* (Gutenberg 43, oil-painting style, 47 pages, 29
plates, 15 cast entries).

## Re-capturing them

They are reproducible, not hand-taken. After a UI change:

```bash
npm install --no-save playwright && npx playwright install chromium   # once
node tools/capture-screenshots.mjs                                    # all sixteen
node tools/capture-screenshots.mjs --only 08,13                       # just these
node tools/capture-screenshots.mjs --book pg-28054                    # a different book
```

The stack must be up (`:8720`, plus the TTS and imagegen services for a fresh bake), and the book
named by `--book` must be **published**. Shots land in `docs/assets/screenshots/` at 2× for crisp
rendering, 1440 px wide, cropped to their content.

## The set

| # | File | Used in | Shows |
|---|---|---|---|
| 1 | `01-books-list.png` | making-books | Admin **Books** list with per-book state. |
| 2 | `02-new-book-wizard.png` | making-books | **New Book** wizard: choose a book + the art-style tiles. |
| 3 | `03-book-detail.png` | making-books | **Book detail**: the bake milestones, Ingested → Published. |
| 4 | `04-review-gate.png` | making-books | The **review gate**: plate list, prompts, cast panel. |
| 5 | `05-portrait-review.png` | making-books | **Portrait review**, ranked by how many pictures each portrait anchors (ADR-0028). |
| 6 | `06-post-render.png` | making-books | **Post-render** review: rendered plates with per-plate Regen. |
| 7 | `07-profile-picker.png` | reading-books | Reader **profile picker**. |
| 8 | `08-shelf.png` | reading-books, README | The **shelf**, mid-download (`Downloading 8/129…`). |
| 9 | `09-reading-surface.png` | reading-books, README | The **reading surface** with a full-page plate. |
| 10 | `10-cast-page.png` | reading-books, README | **Dramatis Personae** — portraits + one-line descriptions. |
| 11 | `11-pictures-picker.png` | reading-books, README | The **Pictures** picker with all sixteen art styles. |
| 12 | `12-search.png` | reading-books | **Search**: 30 hits for "Hyde" with page numbers. |
| 13 | `13-annotations.png` | reading-books | **Annotations** with three colour-filtered highlights. |
| 14 | `14-lightbox.png` | reading-books | A plate **enlarged** full-screen. |
| 15 | `15-settings.png` | reading-books | **Settings**: typeface, size, theme, profile, sync. |

## Notes

- **The README banner** ([`assets/banner.svg`](assets/banner.svg)) is a finished hand-drawn SVG and
  stays that way — no hero screenshot is needed. Replace that file if you ever want a baked one.
- **4, 5 and 6 are shown on a published book**, so they carry a read-only notice and no Approve /
  Regenerate buttons. Those controls only exist while a bake is parked at the gate; catching them
  live would mean holding a bake mid-flight.
- **1 shows a single book** because that is what the capture box had. It will look better on a
  library with several books and a picture set or two grouped under their parent.
