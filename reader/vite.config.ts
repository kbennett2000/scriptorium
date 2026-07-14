import { fileURLToPath, URL } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

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
  },
  test: {
    environment: "jsdom",
    globals: false,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
