# TTS fixtures (`server/tests/fixtures/tts/`)

Recorded/authored responses from the **text-transform-service** (TTS DESIGN §7). These let
P1/P2 be developed and tested on a GPU-less machine (BUILD-PLAN §0 fixture rule). Each file
is the full TTS response envelope `{ "output": {...}, "meta": {...} }` — exactly what
`POST /v1/transform/{name}` returns and what `tools/capture_tts_fixtures.py` writes.

- `cast-mentions/{page_id}.json` — one per page; `output` = `{ "mentions": [...] }` (TTS §7.2).
- `cast-canonicalize/{slug}.json` — one per character; `output` =
  `{ "visual_description", "one_line", "tags" }` (TTS §7.3).
- `scene-update/{page_id}.json` — one per page, consecutive; `output` = the page ledger
  `{ "location", "time_of_day", "atmosphere", "present", "scene_changed", "visual_salience",
  "best_visual_beat", "carry_notes" }` (TTS §7.4). Threaded: each page's ledger is what the
  next page's call receives as `prior_ledger`. In the real captures the frame story stays in
  the Time Traveller's study through `0004` (the model-demonstration beat, the salience peak at
  `0.95`); `0005` carries `scene_changed: true` at the move into the laboratory.
- `illustration-prompt/{page_id}.json` — one per selected page; `output` =
  `{ "prompt", "depicted", "shot", "avoid" }` (TTS §7.5). Stored verbatim as the prompt
  record's `derived` (P5). `0001` and `0006` carry a `meta.warnings` entry ("depicted not in
  cast") that exercises P5's per-page warning capture onto `job.prompt_warnings`.

## Provenance

**Real captures — M1, 2026-07-14, on G434** (TTS `:8712`, Ollama `qwen3.5:9b`). These files
were regenerated from the live text-transform-service via `tools/capture_tts_fixtures.py`,
replacing the hand-written S5/S6/S8 originals. They are the genuine model outputs over the
first six *real* paginated pages of `sources/pg35.txt` — which are entirely the Victorian
dinner-party frame (the Time Traveller's study → laboratory). Note the narrative reality vs.
the old hand-written assumption: the time-jump, 802,701 AD, the Eloi/Morlocks, and Weena do
**not** appear this early, so the captured cast majors are the dinner guests (Time Traveller,
Filby, the Psychologist, the Provincial Mayor, the Medical Man) and the two captured
canonicalizations are `time-traveller` and `filby`. Tests assert schema/shape/cross-references
only, so this re-capture stays green (four latent content-coupled assertions were relaxed to
shape checks in the same change — see CYCLE-LOG "M1").

`cast-canonicalize/weena.json` is a **retained hand-written** fixture from S5: Weena is a
far-future character outside the six-page capture window, so the capture tool does not produce
her canonicalization. No test loads it by name (the cast phase test resolves canonicalize
fixtures by computed slug), so it is kept as a spare far-future example rather than deleted.

Originals were **hand-written at cycle S5** (`cast-*`), **S6** (`scene-update`), **and S8**
(`illustration-prompt`) because TTS was not reachable from the authoring box; a first-person
`"I"` mention on page 0001 still exercises the reducer's pronoun-drop rule.

**To re-capture** (on the LAN with TTS up — warm the model first; the tool does not retry a
cold-start `503`):

```
cd server && TTS_URL=http://<5070-host>:8712 uv run python ../tools/capture_tts_fixtures.py
```

which repaginates `sources/pg35.txt`, calls `cast-mentions` for 6 pages + `cast-canonicalize`
for 2 characters + `scene-update` threaded over 6 pages + `illustration-prompt` over the same
6 pages, and overwrites these files. Never assert exact LLM content in tests
(CLAUDE.md) — tests here assert schema/shape/cross-references only, so a re-capture that
changes wording must stay green.
