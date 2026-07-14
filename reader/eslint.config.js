import js from "@eslint/js";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  // Native platform projects (Capacitor, R5) hold generated config + a copy of the built web assets —
  // not source. android/ios are excluded from lint/typecheck the same way dist is.
  { ignores: ["dist", "android", "ios", "**/*.d.ts"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      globals: { ...globals.browser, ...globals.node },
    },
  },
  // Node-only build scripts (e.g. the R4 dist font/CDN guard) — Node globals, not the browser fence.
  {
    files: ["scripts/**/*.mjs"],
    languageOptions: {
      globals: { ...globals.node },
    },
  },
  // Zero-online-read fence (DESIGN §13, ADR-0003): the reading path performs no network I/O. All
  // server calls live in src/shelf/ and src/sync/ ONLY; fetch/XHR/WebSocket/sendBeacon anywhere else
  // fails lint. This is the mechanical enforcement §13 asks for — do not weaken it.
  {
    files: ["src/**/*.{ts,tsx}"],
    ignores: ["src/shelf/**", "src/sync/**"],
    rules: {
      "no-restricted-syntax": [
        "error",
        {
          selector: "CallExpression[callee.name='fetch']",
          message:
            "Network calls are only allowed in src/shelf/ and src/sync/ (DESIGN §13 zero-online read path).",
        },
        {
          selector: "NewExpression[callee.name='XMLHttpRequest']",
          message:
            "Network calls are only allowed in src/shelf/ and src/sync/ (DESIGN §13 zero-online read path).",
        },
        {
          selector: "NewExpression[callee.name='WebSocket']",
          message:
            "Network calls are only allowed in src/shelf/ and src/sync/ (DESIGN §13 zero-online read path).",
        },
        {
          selector: "MemberExpression[object.name='navigator'][property.name='sendBeacon']",
          message:
            "Network calls are only allowed in src/shelf/ and src/sync/ (DESIGN §13 zero-online read path).",
        },
      ],
    },
  },
);
