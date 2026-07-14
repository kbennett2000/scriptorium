import type { CapacitorConfig } from "@capacitor/cli";

// Capacitor shell config (R5, DESIGN §13/§2). The app ships its built web assets *inside* the APK
// (`webDir: dist`) and loads them from the local WebView — there is deliberately NO `server.url`, so
// the reading path never depends on a live host. The only network the app makes is the shelf/sync
// LAN traffic to the bakery, whose base URL is baked in at build time via VITE_SERVER_URL (see
// shelf/client.ts) and permitted through a scoped network-security-config (not blanket cleartext).
const config: CapacitorConfig = {
  appId: "com.scriptorium.reader",
  appName: "Scriptorium",
  webDir: "dist",
  server: {
    // Serve the local app over http://localhost (not the https default). The bakery is plain-HTTP on
    // the LAN, and an https-origin WebView blocks http requests as Mixed Content regardless of the
    // network-security-config. http://localhost is still a secure context (crypto.subtle etc. work),
    // and http→http to the LAN host is allowed — gated to that host by network_security_config.xml.
    androidScheme: "http",
  },
  android: {
    // Debug builds only — lets `chrome://inspect` attach to the WebView for the emulator walk.
    webContentsDebuggingEnabled: true,
  },
  plugins: {
    // Route the app's fetch()/XHR through native networking on device. The bakery (DESIGN §5) serves
    // no CORS headers and stays untouched this cycle, so a cross-origin browser fetch from
    // http://localhost to the LAN host is blocked by CORS; a native request is not subject to CORS.
    // Cleartext is still gated by network_security_config.xml (OkHttp honours it). Native-only — the
    // desktop PWA keeps using the browser fetch, and only shelf/ + sync/ ever call the network anyway.
    CapacitorHttp: { enabled: true },
  },
};

export default config;
