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

# Build the admin-ui production bundle (into admin-ui/dist).
admin-build:
    cd admin-ui && npm run build

# Build the reader and assert the dist vendors its fonts with no CDN references (R4 zero-online guard).
reader-build-check:
    cd reader && npm run build:check

# Build a debug Android APK (R5): web build → cap sync → gradle assembleDebug. Needs the Android SDK +
# JDK 17 (see reader/BUILDING.md). Pass a LAN bakery URL for an on-device build, e.g.
#   VITE_SERVER_URL=http://192.168.1.10:8720 just android-build
# Output: reader/android/app/build/outputs/apk/debug/app-debug.apk
android-build:
    cd reader && npm run android:build

# --- generation ---

# Regenerate shared TypeScript types from the JSON Schemas (deterministic).
gen-types:
    node shared/gen-types.mjs

# --- tests ---

# Run the server test suite (offline; GPU/network tests skipped by default).
server-test:
    cd server && uv run pytest

# Run the admin-ui test suite (Vitest + RTL + jsdom; offline, stubbed fetch).
admin-test:
    cd admin-ui && npm run test

# Run the reader Playwright acceptance (R3 two-device sync). Spins up a fresh FastAPI server + the
# Vite dev server (fixture mode, proxied) itself; needs Chromium (npx playwright install chromium).
reader-e2e:
    cd reader && npm run test:e2e

# Run every test suite.
test-all: server-test admin-test

# --- lint ---

# Lint everything: ruff (server) + eslint & tsc (reader, admin-ui).
lint-all:
    cd server && uv run ruff check .
    cd reader && npm run lint && npm run typecheck
    cd admin-ui && npm run lint && npm run typecheck
