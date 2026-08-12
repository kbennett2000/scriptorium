# server — the Scriptorium bakery

Python 3.12 / FastAPI. This is the orchestrator: it runs the bake pipeline, stores the library,
handles annotation sync, and serves the two web apps (reader at `/`, admin at `/admin`) plus the
`/api` and `/health` endpoints on port **8720**.

Heavy AI work is delegated over the LAN to the GPU-box services (`TTS_URL`, `IMAGEGEN_URL`); with
those unset the server still boots and runs — books simply park at "waiting for the graphics card."

```sh
uv sync
uv run pytest                 # offline; GPU/network suites are opt-in
uv run ruff check .
uv run uvicorn scriptorium.app:app --host 0.0.0.0 --port 8720
```

Configuration is all environment variables (see [`src/scriptorium/config.py`](src/scriptorium/config.py)),
documented for humans in the **[self-hosting guide](../docs/guide/self-hosting.md#configuration)**.
Off-box backups of the data dir: [`deploy/README.md`](deploy/README.md).

The fastest way to a running server is the repo-root helpers: `./scripts/setup.sh` then
`./scripts/start.sh` (or `.ps1` on Windows).
