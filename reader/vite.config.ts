import { fileURLToPath, URL } from "node:url";

import react from "@vitejs/plugin-react";
import { configDefaults, defineConfig } from "vitest/config";

// The reader is served at the site root by the i5 server (DESIGN §11).
export default defineConfig({
  base: "/",
  plugins: [react()],
  resolve: {
    alias: {
      "@scriptorium/shared": fileURLToPath(
        new URL("../shared/types/index.d.ts", import.meta.url),
      ),
    },
  },
  server: {
    // VITE_FIXTURE_BUNDLE mode inlines the canonical server fixture via import.meta.glob; the dev
    // server must be allowed to read it across the package boundary (build reads from disk directly).
    fs: {
      allow: [
        fileURLToPath(new URL(".", import.meta.url)),
        fileURLToPath(new URL("../server/tests/fixtures/bundle", import.meta.url)),
      ],
    },
    // Proxy the API + health check to the FastAPI server so the browser sees them same-origin (the
    // server sets no CORS headers). Used by `reader-dev` against a local server and by the Playwright
    // acceptance (VITE_PROXY_TARGET overrides the default local port).
    proxy: {
      "/api": { target: process.env.VITE_PROXY_TARGET ?? "http://127.0.0.1:8720", changeOrigin: true },
      "/health": { target: process.env.VITE_PROXY_TARGET ?? "http://127.0.0.1:8720", changeOrigin: true },
    },
  },
  test: {
    environment: "jsdom",
    globals: false,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    // e2e/ holds Playwright specs (also `.spec.ts`); they run under `npm run test:e2e`, not Vitest.
    exclude: [...configDefaults.exclude, "e2e/**"],
  },
});
