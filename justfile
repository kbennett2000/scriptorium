# Scriptorium task runner. Run `just` to list recipes.
# Requires: uv (server), Node 20+ / npm (reader, admin-ui, shared).

set shell := ["bash", "-uc"]

# Default: show the recipe list.
default:
    @just --list

# --- dev servers ---

# Run the FastAPI server with autoreload (port from SCRIPTORIUM_PORT, default 8720).
server-dev:
    cd server && uv run uvicorn scriptorium.app:app --reload --host 0.0.0.0 --port "${SCRIPTORIUM_PORT:-8720}"

# Run the reader Vite dev server.
reader-dev:
    cd reader && npm run dev

# Run the admin-ui Vite dev server.
admin-dev:
    cd admin-ui && npm run dev

# --- generation ---

# Regenerate shared TypeScript types from the JSON Schemas (deterministic).
gen-types:
    node shared/gen-types.mjs

# --- tests ---

# Run the server test suite (offline; GPU/network tests skipped by default).
server-test:
    cd server && uv run pytest

# Run every test suite. (Client test suites are added in later cycles.)
test-all: server-test

# --- lint ---

# Lint everything: ruff (server) + eslint & tsc (reader, admin-ui).
lint-all:
    cd server && uv run ruff check .
    cd reader && npm run lint && npm run typecheck
    cd admin-ui && npm run lint && npm run typecheck
