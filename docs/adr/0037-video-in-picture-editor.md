# ADR 0037: "bring a picture to life" — per-plate video in the reader's picture editor

- **Status:** Accepted
- **Date:** 2026-08-14
- **Relates to:** ADR-0033 (per-plate picture edits), ADR-0034 (edit fidelity + harness parity),
  ADR-0035 (edits scoped per set), ADR-0014 (per-user art sets), DESIGN §8, §13.
- **Depends on (ops):** imagegen-service `POST /animate` (WAN 2.2) merged to that service's master and
  deployed with WAN models fetched. Until then the feature stays hidden (readiness gate).

## Context

imagegen-service gained a synchronous video endpoint — `POST /animate` takes a base64 still and
returns raw mp4 bytes (WAN 2.2 TI2V 5B / Remix 14B). The post-publish **Edit picture** screen already
runs a candidate → accept → commit → overlay-checkout pipeline for image edits (ADR-0033/0034/0035).
We surface animation there: from a plate's current picture a reader renders a short clip; if they
**accept** it, a **play icon** appears on that plate in the reader and clicking it plays the clip —
fully offline, like every other reader asset.

## Decision

**A per-plate video is an additive, per-`(scope, plate_id)` overlay asset**, produced by the same
candidate/accept gate as an image edit and stored beside the image overlay in the private
`artsets/{user}/{book}/edits/` store. The published bundle and `pages/*.json` are never touched.

- **Animate from the current committed picture.** The start frame is `_current_plate_png` for the
  active scope (prior edit → set plate → book plate) — the same source the img2img start frame uses.
  To animate an edit, accept the picture edit first; the video is independent of the image edit and
  never changes the picture. It also works with no edit at all.
- **Synchronous render.** A WAN render takes minutes (and the first job after an image job pauses to
  swap the GPU model set), so `POST …/video-candidate` holds the connection open behind a "this takes
  a few minutes" spinner — mirroring `/animate` and the image-candidate flow. `GpuUnavailable → 503`,
  never a fallback.
- **One imagegen service.** `/animate` is the same service as `/generate`, so the bakery reuses
  `cfg.imagegen_url` and adds `animate()` + `video_health()` to `RealImagegenClient`/`FakeImagegen` —
  no new config or client. The animate model wire ids are `wan-5b` / `remix-14b`.
- **Storage + schema.** The accepted clip lands at `images/video/plates/{scope}/{plate_id}.mp4`; the
  `artset-edits` entry gains an optional `video` descriptor (`motion_prompt`, `model`, `frames`,
  `fps`, `seed`, `created`) whose *presence* drives the reader's play icon. A video-only accept seeds
  a minimal entry from the current caption + subject prompt so nothing visible changes but the clip.
- **Delivery + read path.** `"images/video/**"` joins `READER_REQUIRED` (the shared book/overlay
  glob) so the overlay manifest delivers the mp4 offline. `OverlayImageBundleReader` gains
  `hasVideo(plateId)` / `videoUrl(plateId)` (an offline `video/mp4` blob URL, active scope only);
  `Plate.tsx` overlays a play button that swaps the still for an inline `<video>`.
- **Reader controls.** The editor's "Bring to life" section exposes a motion prompt, model picker
  (from the service's ready models), and frames/fps/seed, plus **Render video** → preview → **Accept
  video**. It is hidden unless `plate_context` reports `video_available`.

## Consequences

- A reader can animate any plate's current picture; the accepted clip plays offline with a play icon,
  scoped per set exactly like an image edit (a clip made on the comic set shows only there).
- Video and image edits are independent additive commits on the same `(scope, plate_id)` entry.
- The reader's zero-online read path holds: every video call lives in `shelf/` (ESLint-enforced) and
  playback is from an OPFS blob URL, never a fetch. The candidate → **Accept** step is the review
  gate. New `animate` params are forwarded only when set; `FakeImagegen` stays deterministic; tests
  assert request params / overlay paths / manifest delivery, never clip content.
- **Deferred:** first-last-frame ("animate toward an end picture", the endpoint supports it), cover /
  portrait video, and an async job/poll flow (only if the synchronous hold proves fragile in the
  field).
