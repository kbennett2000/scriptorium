import { fileURLToPath, URL } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The admin UI is served under /admin by the i5 server (DESIGN §11.3).
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
});
