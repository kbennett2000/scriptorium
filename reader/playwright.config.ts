import { fileURLToPath } from "node:url";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { defineConfig, devices } from "@playwright/test";

// The R3 acceptance harness (DESIGN §12/§13). Drives two isolated browser contexts against a live
// FastAPI server through the Vite dev proxy, so the browser sees /api and /health same-origin (the
// server sets no CORS headers and is untouched this cycle). The reader runs in VITE_FIXTURE_BUNDLE
// mode: the committed fixture book opens with no library/checkout, and the sync engine + profile
// picker are exercised end-to-end.
//
// The server gets a FRESH data dir per run (mkdtemp) so accumulated sync state can't skew convergence
// or furthest-read assertions. A non-default port avoids clashing with a running `just server-dev`.

const SERVER_PORT = 8799;
const READER_PORT = 5199;
const SERVER_DIR = fileURLToPath(new URL("../server", import.meta.url));
const DATA_DIR = mkdtempSync(join(tmpdir(), "scriptorium-e2e-"));

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${READER_PORT}`,
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `uv run uvicorn scriptorium.app:app --host 127.0.0.1 --port ${SERVER_PORT}`,
      cwd: SERVER_DIR,
      url: `http://127.0.0.1:${SERVER_PORT}/health`,
      timeout: 120_000,
      reuseExistingServer: false,
      env: { SCRIPTORIUM_DATA: DATA_DIR, SCRIPTORIUM_PORT: String(SERVER_PORT) },
    },
    {
      command: `npm run dev -- --port ${READER_PORT} --strictPort`,
      url: `http://127.0.0.1:${READER_PORT}`,
      timeout: 120_000,
      reuseExistingServer: false,
      env: {
        VITE_FIXTURE_BUNDLE: "1",
        VITE_PROXY_TARGET: `http://127.0.0.1:${SERVER_PORT}`,
      },
    },
  ],
});
