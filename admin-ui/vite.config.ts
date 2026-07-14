import { fileURLToPath, URL } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The admin UI is served under /admin by the i5 server (DESIGN §11.3). In dev, Vite proxies the
// admin API + health probe to the FastAPI server on :8720 so the app can talk to a real backend
// without CORS. (admin-ui is a LAN network client — the reader's zero-online fence does NOT apply.)
export default defineConfig({
  base: "/admin/",
  plugins: [react()],
  resolve: {
    alias: {
      "@scriptorium/shared": fileURLToPath(
        new URL("../shared/types/index.d.ts", import.meta.url),
      ),
    },
  },
  server: {
    proxy: {
      "/api": "http://localhost:8720",
      "/health": "http://localhost:8720",
    },
  },
  test: {
    environment: "jsdom",
    globals: false,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
