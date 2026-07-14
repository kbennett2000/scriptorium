/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Optional dev override for the server base URL (e.g. http://192.168.1.10:8720). Prod = same-origin. */
  readonly VITE_SERVER_URL?: string;
  /** Dev flag: "1" loads the committed fixture bundle with no backend (see FixtureBundleReader). */
  readonly VITE_FIXTURE_BUNDLE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
