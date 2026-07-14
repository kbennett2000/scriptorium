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
  test: {
    environment: "jsdom",
    globals: false,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
