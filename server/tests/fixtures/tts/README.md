# TTS fixtures (`server/tests/fixtures/tts/`)

Recorded/authored responses from the **text-transform-service** (TTS DESIGN §7). These let
P1/P2 be developed and tested on a GPU-less machine (BUILD-PLAN §0 fixture rule). Each file
is the full TTS response envelope `{ "output": {...}, "meta": {...} }` — exactly what
`POST /v1/transform/{name}` returns and what `tools/capture_tts_fixtures.py` writes.

- `cast-mentions/{page_id}.json` — one per page; `output` = `{ "mentions": [...] }` (TTS §7.2).
- `cast-canonicalize/{slug}.json` — one per character; `output` =
  `{ "visual_description", "one_line", "tags" }` (TTS §7.3).

## Provenance

**Hand-written at cycle S5.** TTS (on the RTX 5070) was **not reachable** from the authoring
box (`TTS_URL` unset / LAN-only), so these were written by hand to the TTS output schemas —
not captured from a live model. They are schema-shaped and internally consistent (a Time
Machine cast: the Time Traveller, Weena, the Eloi/Morlocks, the dinner guests), and include a
first-person `"I"` mention on page 0001 to exercise the reducer's pronoun-drop rule.

**Replace with real captures at the first opportunity:** on the LAN, with TTS T5 up, run

```
cd server && TTS_URL=http://<5070-host>:8712 uv run python ../tools/capture_tts_fixtures.py
```

which repaginates `sources/pg35.txt`, calls `cast-mentions` for 6 pages + `cast-canonicalize`
for 2 characters, and overwrites these files. Never assert exact LLM content in tests
(CLAUDE.md) — tests here assert schema/shape/cross-references only, so a re-capture that
changes wording must stay green.
