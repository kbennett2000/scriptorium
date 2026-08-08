# ADR 0020: AUTO_START — mark a freshly-ingested job started (unattended runs)

- **Status:** Accepted
- **Date:** 2026-08-08
- **Pairs with:** [ADR-0015](0015-auto-approve.md) (`AUTO_APPROVE`). Together they enable a full
  hands-off "kick off → wake up to a done book" run on a single-user box.

## Context

The bake pipeline has two human halts. ADR-0015's `AUTO_APPROVE` already automates the second (the
review gate). The first remains: `POST /api/admin/books` runs P0 (ingest + paginate) and leaves the
job at `ingested` with `started=False`; the runner skips any job where `not job.started`
(`runner.py`), so it idles until a human calls `POST /api/admin/jobs/{id}/start`. That Start click
exists only to open the **pre-P1 chapter-edit window** (`PUT /books/{id}/chapters`, allowed only at
`ingested`). For an owner who just wants to load a book, set settings, and walk away, it is pure
friction with no automated path.

## Decision

Add an opt-in config flag `auto_start` (env `AUTO_START`, default **false**), mirroring
`auto_approve`. When true, `run_p0` sets `job.started = True` on the freshly-ingested job before it
is saved, so the runner advances it immediately without a Start click.

- The job still **ingests and paginates first** — auto-start only flips the `started` flag; it does
  not skip or reorder any phase.
- It **closes the pre-P1 chapter-edit window** (the job leaves `ingested` as soon as the runner
  ticks). That window is only reachable with the flag **off** — the deliberate tradeoff for
  unattended use.
- No new endpoint, no new state, no change to the state chain or transition table.

## Why this does not weaken any invariant

- **Not a render bypass.** `AUTO_START` only affects when a job leaves `ingested`; it does not touch
  the review gate. Rendering still fires only from `approved`, reached only via `approve_job` (human
  click, or `AUTO_APPROVE`'s same-guard path). With `AUTO_START=1` but `AUTO_APPROVE=0`, a job runs
  itself to `prompts_draft` and then **still waits for the human review gate**.
- **Default off ⇒ byte-identical default behavior.** Every existing test and the shipped default
  keep the Start click; `test_auto_approve.py` and the full suite stay green.
- **Owner intent, relocated.** Like ADR-0015 moved the approval click to the upstream "make this
  book" intent, this moves the Start click there too — the owner opting into `AUTO_START` *is* the
  decision to begin.

## Consequences

- With `AUTO_START=1` **and** `AUTO_APPROVE=1`, creating a book in the wizard runs it unattended all
  the way to `published` (start → mentions → cast → ledger → select → prompts → auto-approve →
  render → publish), no clicks.
- The chapter-edit window is unavailable while `AUTO_START` is on; an owner who needs it runs with
  the flag off (edit, then Start).
- The admin status endpoint exposes `unattended = auto_start and auto_approve` so the UI can tell the
  owner no click is coming.
- Single-user LAN dev box opts in via `AUTO_START=1` (alongside `TTS_URL`/`IMAGEGEN_URL`/
  `AUTO_APPROVE`); the flag is not set in any test or default config.
