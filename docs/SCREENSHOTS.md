# Screenshots

Every screenshot in the docs is **real** — captured from a live stack, never mocked up. Three books
were baked to produce them, because several shots only exist while a bake is *parked at a gate*:

| Book | Style | Left at | Gives us |
|---|---|---|---|
| *The Strange Case of Dr. Jekyll and Mr. Hyde* (Gutenberg 43) | oil-painting | **published** | the whole reader, plus book detail + post-render |
| *The Yellow Wallpaper* (Gutenberg 1952) | watercolor | **`prompts_draft`** | the review gate with live Approve/Save controls |
| *The Legend of Sleepy Hollow* (Gutenberg 41) | engraving | **`portraits_review`** | the portrait gate, ranked, with live Regenerate |

## Re-capturing them

They are reproducible, not hand-taken. After a UI change:

```bash
npm install --no-save playwright && npx playwright install chromium   # once
node tools/capture-screenshots.mjs                                    # all fifteen
node tools/capture-screenshots.mjs --only 08,13                       # just these
node tools/capture-screenshots.mjs --only 04 --book pg-1952           # a specific book
python3 tools/postprocess-screenshots.py                              # ALWAYS run this after
```

`postprocess-screenshots.py` crops dead margins and quantises to a 256-colour palette — about a 2.6x
saving (11.4 MB → 4.3 MB) and visually lossless on flat UI. **Run it after every capture**, or the
repo gains several MB of mostly-white PNG.

### The two gate shots need a parked bake

`04` and `05` photograph controls that only exist mid-bake, so they cannot be taken against a
published book:

- **Start the server without `AUTO_APPROVE`.** With it set, a bake self-approves straight through
  the plate gate (ADR-0015) and `04` is only ever available read-only.
- **`04`** needs a book resting at `prompts_draft` — pass `--book` for it.
- **`05`** needs one at `portraits_review`, which means baking with `"portrait_review": true`.
- Capture these *before* letting those books finish. A plain `node tools/capture-screenshots.mjs`
  run re-shoots them against `--book`'s default and will overwrite a good gate shot with the
  read-only view.

## The set

| # | File | Used in | Shows |
|---|---|---|---|
| 1 | `01-books-list.png` | making-books | Admin **Books** list — three books, three different states. |
| 2 | `02-new-book-wizard.png` | making-books | **New Book** wizard: choose a book + the art-style tiles. |
| 3 | `03-book-detail.png` | making-books | **Book detail**: the bake milestones, Ingested → Published. |
| 4 | `04-review-gate.png` | making-books | The **review gate**, live: editable prompts, cast panel, "depicted not in cast" warnings. |
| 5 | `05-portrait-review.png` | making-books | **Portrait review**, live — ranked by how many pictures each portrait anchors (ADR-0028). |
| 6 | `06-post-render.png` | making-books | **Post-render** review: rendered plates with per-plate Regen. |
| 7 | `07-profile-picker.png` | reading-books | Reader **profile picker**. |
| 8 | `08-shelf.png` | reading-books, README | The **shelf**, mid-download (`Downloading 7/101…`). |
| 9 | `09-reading-surface.png` | reading-books, README | The **reading surface** with a full-page plate. |
| 10 | `10-cast-page.png` | reading-books, README | **Dramatis Personae** — portraits + one-line descriptions. |
| 11 | `11-pictures-picker.png` | reading-books, README | The **Pictures** picker with all sixteen art styles. |
| 12 | `12-search.png` | reading-books | **Search**: hits for "Hyde" with page numbers. |
| 13 | `13-annotations.png` | reading-books | **Annotations** with three colour-filtered highlights. |
| 14 | `14-lightbox.png` | reading-books | A plate **enlarged** full-screen. |
| 15 | `15-settings.png` | reading-books | **Settings**: typeface, size, theme, profile, sync. |

## Notes

- **The README banner** ([`assets/banner.svg`](assets/banner.svg)) is a finished hand-drawn SVG and
  stays that way — no hero screenshot is needed. Replace that file if you ever want a baked one.
- **`06` is shown on a published book.** `rendered → published` is an automatic phase (P8) with no
  human gate, so the post-render screen is only "live" for the ~5 s between them. The page itself is
  identical; only the Regen buttons are inert.
- **`08` needs a throttle.** A 1.6 MB bundle over localhost finishes in well under a second, so the
  capture script slows the transfer over CDP or there is no progress line to photograph.
- **Shot heights vary** because each is cropped to its own content. That is deliberate — a fixed
  viewport left most of these two-thirds white.
