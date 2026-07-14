import { App } from "@capacitor/app";
import { Capacitor } from "@capacitor/core";
import { Style, StatusBar } from "@capacitor/status-bar";

import { handleBack } from "./back";

// Native (Android/iOS) shell wiring (R5, kickoff): the hardware back button and status-bar theming.
// Everything here is a no-op on the web (guarded by isNativePlatform), so the PWA and Playwright
// paths are untouched. Feature modules stay platform-agnostic — they register intent via ./back and
// set prefs via the theme; only this module knows about Capacitor plugins.

let started = false;

/**
 * Wire the hardware/gesture Back button to our handler stack: an open overlay closes, else the reader
 * steps back a page, else it returns to the shelf, and only when nothing consumes it does the app
 * background (minimize — NEVER exitApp; Back must not kill the app). Idempotent; safe to call once at
 * App mount.
 */
export function initNativeShell(): void {
  if (started || !Capacitor.isNativePlatform()) return;
  started = true;
  void App.addListener("backButton", () => {
    if (!handleBack()) void App.minimizeApp();
  });
  // The status bar draws over the WebView (Android 15+ is edge-to-edge by default and ignores
  // setOverlaysWebView); the top/bottom bars keep clear of it via CSS safe-area insets (index.css
  // --safe-top/--safe-bottom). Only the icon style is set here, tracking the theme (applyStatusBarForTheme).
}

/** Match the status bar to the active reading theme (light/sepia → dark icons; dark → light icons). */
export function applyStatusBarForTheme(theme: "light" | "sepia" | "dark"): void {
  if (!Capacitor.isNativePlatform()) return;
  // Style.Light = light background ⇒ dark content; Style.Dark = dark background ⇒ light content.
  void StatusBar.setStyle({ style: theme === "dark" ? Style.Dark : Style.Light });
}
