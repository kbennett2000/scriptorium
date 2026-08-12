// Capture every screenshot in docs/SCREENSHOTS.md against a live stack.
//
//   node tools/capture-screenshots.mjs [--book pg-43] [--base http://localhost:8720] [--only 08,13]
//
// Needs Playwright, which is deliberately NOT a dependency of this repo (it is a docs chore, not
// part of the build):
//
//   npm install --no-save playwright && npx playwright install chromium
//
// Most shots are just a route. The interesting ones need the app to be in a particular STATE, and
// getting there is most of this file:
//   * 08 — the shelf mid-download. A 2.8 MB bundle over localhost finishes in well under a second,
//     so the transfer is throttled via CDP or the progress line never exists to photograph.
//   * 13 — the annotations panel with real highlights. They are created through the Selection API
//     because Reader listens for `selectionchange` and requires the range to sit inside `.page-text`.
//   * 11 — the picture-set picker only lists "Default" until a set exists; the art styles live
//     behind "New set".
// And one trap worth knowing: opening a book mounts a "Dramatis personae" dialog over the toolbar.
// Leaving it up silently corrupts every later shot, so `dismiss()` runs before each capture.

import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const argv = process.argv.slice(2);
const arg = (name, fallback) => {
  const i = argv.indexOf(`--${name}`);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : fallback;
};

const BASE = arg("base", "http://localhost:8720");
const BOOK = arg("book", "pg-43");
const ONLY = arg("only", null) ? new Set(arg("only").split(",")) : null;
const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const OUT = path.join(REPO, "docs/assets/screenshots");
const W = 1440, H = 960;

mkdirSync(OUT, { recursive: true });
const done = [], skipped = [];
const wants = (n) => !ONLY || ONLY.has(n.split("-")[0]);

async function shot(page, name, opts = {}) {
  await page.waitForTimeout(350);
  await page.screenshot({ path: path.join(OUT, `${name}.png`), ...opts });
  done.push(name);
  console.log(`  ✓ ${name}.png`);
}

/** Shrink the viewport to the content so a short page is not mostly dead space. */
async function fit(page, { min = 400, max = 1700 } = {}) {
  const h = await page.evaluate(() =>
    Math.max(document.body.scrollHeight, document.documentElement.scrollHeight));
  await page.setViewportSize({ width: W, height: Math.min(Math.max(h, min), max) });
  await page.waitForTimeout(300);
}

/** Clip from the top through the bottom of `selector`. The app gives its shell a full-viewport
 *  min-height, so `fit()` alone cannot shrink a short page — this trims to the real content. */
async function clipTo(page, selector) {
  return page.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    return { x: 0, y: 0, width: window.innerWidth,
             height: Math.ceil(el.getBoundingClientRect().bottom + 28) };
  }, selector);
}

/** Clip from the top to just ABOVE the first block whose text starts with `stopAt`.
 *  Case-insensitive on purpose: the admin headings are uppercased in CSS, so the DOM text of the
 *  "DELETE THIS BOOK PERMANENTLY" panel is actually "Delete this book permanently". */
async function clipBefore(page, stopAt) {
  return page.evaluate((needle) => {
    const el = [...document.querySelectorAll("section,div,form,table")]
      .find((n) => n.textContent.trim().toLowerCase().startsWith(needle.toLowerCase()));
    if (!el) return null;
    const top = el.getBoundingClientRect().top;
    if (top < 80) return null; // matched a wrapper, not the panel — better unclipped than empty
    return { x: 0, y: 0, width: window.innerWidth, height: Math.ceil(top - 8) };
  }, stopAt);
}

/** Clip to the lowest visible text in the page. `fit()` cannot shrink a short screen because the
 *  app shell claims the full viewport height, which otherwise leaves shots mostly blank. */
async function clipToContent(page, { min = 240, trimWidth = false } = {}) {
  return page.evaluate(({ minH, trimW }) => {
    let bottom = 0, right = 0;
    for (const el of document.body.querySelectorAll("*")) {
      // Leaves only. Containers and modal backdrops span the whole viewport, so measuring them
      // reports the viewport back and the clip trims nothing.
      const leafish = el.children.length === 0 || ["IMG", "INPUT", "SELECT"].includes(el.tagName);
      if (!leafish) continue;
      if (!el.textContent.trim() && !["IMG", "INPUT", "SELECT"].includes(el.tagName)) continue;
      const r = el.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) continue;
      if (r.bottom > bottom && r.bottom <= window.innerHeight) bottom = r.bottom;
      if (r.right > right && r.right <= window.innerWidth) right = r.right;
    }
    if (!bottom) return null;
    return {
      x: 0, y: 0,
      width: trimW && right ? Math.min(Math.ceil(right + 24), window.innerWidth) : window.innerWidth,
      height: Math.max(Math.ceil(bottom + 24), minH),
    };
  }, { minH: min, trimW: trimWidth });
}

async function dismiss(page) {
  for (let i = 0; i < 5; i++) {
    const dlg = page.locator('[role="dialog"]:visible').first();
    if (!(await dlg.count())) return;
    const d = dlg.getByRole("button", { name: /^(Done|Close)$/ }).first();
    const c = page.locator('[aria-label^="Close"]:visible').first();
    if (await d.count()) await d.click().catch(() => {});
    else if (await c.count()) await c.click().catch(() => {});
    else await page.keyboard.press("Escape");
    await page.waitForTimeout(450);
  }
}

async function openPanel(page, label) {
  await dismiss(page);
  const btn = page.locator(`[aria-label="${label}"]`).first();
  if (!(await btn.count())) return false;
  await btn.waitFor({ state: "visible", timeout: 60000 }).catch(() => {});
  await btn.click();
  await page.waitForTimeout(1400);
  return true;
}

/** Select `len` chars from the nth long text node of .page-text — fires `selectionchange`. */
async function selectRange(page, nth, skip, len) {
  return page.evaluate(({ nth, skip, len }) => {
    const container = document.querySelector(".page-text");
    if (!container) return { ok: false, why: "no .page-text" };
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
    const nodes = [];
    let n;
    while ((n = walker.nextNode())) if (n.textContent.trim().length > 150) nodes.push(n);
    if (!nodes[nth]) return { ok: false, why: `only ${nodes.length} long text nodes` };
    const node = nodes[nth];
    const start = Math.min(skip, Math.max(0, node.textContent.length - len - 1));
    const range = document.createRange();
    range.setStart(node, start);
    range.setEnd(node, Math.min(start + len, node.textContent.length));
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    return { ok: true };
  }, { nth, skip, len });
}

async function captureAdmin(ctx) {
  const page = await ctx.newPage();
  const routes = [
    // `sel` trims to that element's bottom; `stopAt` trims to just above that block.
    ["01-books-list", "#/", null, "table"],
    ["02-new-book-wizard", "#/new", null, null],
    // Stop before the "delete this book permanently" panel — the milestones are the subject.
    ["03-book-detail", `#/book/${BOOK}`, "Delete this book", null],
    ["04-review-gate", `#/book/${BOOK}/review`, null, null],
    ["05-portrait-review", `#/book/${BOOK}/portraits`, null, null],
    ["06-post-render", `#/book/${BOOK}/postrender`, null, null],
  ];
  for (const [name, hash, stopAt, sel] of routes) {
    if (!wants(name)) continue;
    await page.setViewportSize({ width: W, height: H });
    await page.goto(`${BASE}/admin/${hash}`, { waitUntil: "networkidle" });
    await page.waitForTimeout(1400);
    await fit(page);
    const clip = stopAt ? await clipBefore(page, stopAt) : sel ? await clipTo(page, sel) : null;
    await shot(page, name, clip ? { clip } : {});
  }
  await page.close();
}

async function captureReader(ctx) {
  const page = await ctx.newPage();
  page.on("dialog", (d) => d.accept().catch(() => {}));   // the Remove confirmation
  const cdp = await ctx.newCDPSession(page);
  await cdp.send("Network.enable");

  await page.setViewportSize({ width: W, height: H });
  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.waitForTimeout(2500);

  const picker = page.locator("button.profile-choice");
  if (await picker.count()) {
    if (wants("07-profile-picker")) {
      await fit(page);
      await shot(page, "07-profile-picker", await clipToContent(page).then((c) => (c ? { clip: c } : {})));
    }
    await page.setViewportSize({ width: W, height: H });
    await picker.first().click();
    await page.waitForTimeout(2500);
  } else skipped.push("07-profile-picker (device already has an active profile)");

  await page.waitForFunction(
    () => [...document.querySelectorAll("button")]
      .some((b) => /^(Download|Resume download|Open)$/.test(b.textContent.trim())),
    { timeout: 60000 });

  // Evict first so the download is real, and throttle so the progress line lasts long enough.
  const remove = page.getByRole("button", { name: /^Remove$/ }).first();
  if (await remove.count()) { await remove.click(); await page.waitForTimeout(2500); }
  await cdp.send("Network.emulateNetworkConditions", {
    offline: false, latency: 120, downloadThroughput: 180 * 1024, uploadThroughput: 180 * 1024,
  });
  const dl = page.getByRole("button", { name: /^(Download|Resume download)$/ }).first();
  if (await dl.count()) {
    await dl.click();
    await page.waitForFunction(() => /Downloading\s+\d+\/\d+/.test(document.body.innerText),
      { timeout: 30000 }).catch(() => console.log("   ! never saw a progress line"));
    await page.waitForTimeout(1200);
  }
  if (wants("08-shelf")) {
    await fit(page);
    await shot(page, "08-shelf", await clipToContent(page).then((c) => (c ? { clip: c } : {})));
  }
  await page.setViewportSize({ width: W, height: H });

  await cdp.send("Network.emulateNetworkConditions", {
    offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1,
  });
  const ok = await page.waitForFunction(
    () => [...document.querySelectorAll("button")].some((b) => b.textContent.trim() === "Open"),
    { timeout: 300000 }).then(() => true).catch(() => false);
  if (!ok) { skipped.push("09..15 (download never finished)"); await page.close(); return; }

  await page.waitForTimeout(1500);
  await page.getByRole("button", { name: /^Open$/ }).first().click();
  await page.waitForTimeout(4000);
  await dismiss(page);

  // Illustrations are sparse; walk forward until one is on screen.
  for (let i = 0; i < 40; i++) {
    if (await page.locator(".plate-img:visible").count()) break;
    await page.keyboard.press("ArrowRight");
    await page.waitForTimeout(420);
  }
  await page.waitForTimeout(1200);
  await dismiss(page);
  if (wants("09-reading-surface")) await shot(page, "09-reading-surface");

  if (wants("14-lightbox")) {
    const plate = page.locator(".plate-img:visible").first();
    if (await plate.count()) {
      await plate.click();
      await page.waitForTimeout(1400);
      await shot(page, "14-lightbox");
      await page.keyboard.press("Escape");
      await page.waitForTimeout(800);
      await dismiss(page);
    } else skipped.push("14-lightbox (no plate on screen)");
  }

  // Real highlights, so the annotations panel is not just an empty state.
  if (wants("13-annotations")) {
    for (const [i, color] of ["yellow", "blue", "green"].entries()) {
      const r = await selectRange(page, i, 20 + i * 20, 150 - i * 20);
      if (!r.ok) continue;
      await page.waitForTimeout(800);
      // The floating bar is positioned from the selection rect and can land outside the viewport,
      // so dispatch the click in-page rather than letting the visibility check veto it.
      await page.evaluate((c) => document.querySelector(`[aria-label="Highlight ${c}"]`)?.click(), color);
      await page.waitForTimeout(900);
      await page.evaluate(() => window.getSelection()?.removeAllRanges());
      await page.waitForTimeout(300);
    }
  }

  // Read on, so the no-spoiler cast filter reveals more than the first character.
  for (let i = 0; i < 45; i++) { await page.keyboard.press("ArrowRight"); await page.waitForTimeout(160); }
  await page.waitForTimeout(1500);
  await dismiss(page);

  for (const [name, label] of [
    ["10-cast-page", "Cast"],
    ["11-pictures-picker", "Pictures"],
    ["12-search", "Search"],
    ["13-annotations", "Annotations"],
    ["15-settings", "Settings"],
  ]) {
    if (!wants(name)) continue;
    if (!(await openPanel(page, label))) { skipped.push(`${name} (no "${label}" control)`); continue; }
    if (label === "Search") {
      const box = page.locator('input[type="search"], input[type="text"]').first();
      if (await box.count()) { await box.fill("Hyde"); await box.press("Enter"); await page.waitForTimeout(1800); }
    }
    if (label === "Pictures") {
      const ns = page.getByText(/New set/).first();   // the art styles live behind this
      if (await ns.count()) { await ns.click(); await page.waitForTimeout(1600); }
      // All sixteen styles only fit in a tall viewport — the panel scrolls internally, so
      // `fit()` cannot discover the list's real height from the document.
      await page.setViewportSize({ width: W, height: 1800 });
      await page.waitForTimeout(700);
    }
    if (["10-cast-page", "11-pictures-picker", "15-settings"].includes(name)) await fit(page);
    // These two sit in a narrow column, so trim the empty half of the canvas too.
    const clip = ["15-settings", "11-pictures-picker"].includes(name)
      ? await clipToContent(page, { trimWidth: true })
      : null;
    await shot(page, name, clip ? { clip } : {});
    await page.setViewportSize({ width: W, height: H });
    await dismiss(page);
  }
  await page.close();
}

// Shot numbers each half is responsible for, so `--only 05` doesn't drag the reader through a
// download it has no shot to take (and time out when nothing is published yet).
const ADMIN_SHOTS = ["01", "02", "03", "04", "05", "06"];
const READER_SHOTS = ["07", "08", "09", "10", "11", "12", "13", "14", "15"];
const needs = (nums) => nums.some((n) => wants(`${n}-`));

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: 2 });
try {
  if (needs(ADMIN_SHOTS)) await captureAdmin(ctx);
  if (needs(READER_SHOTS)) await captureReader(ctx);
} finally {
  await browser.close();
}
console.log(`\ncaptured ${done.length}: ${done.join(", ")}`);
if (skipped.length) console.log(`SKIPPED ${skipped.length}:\n  - ${skipped.join("\n  - ")}`);
