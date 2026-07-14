import { expect, test, type BrowserContext, type Page } from "@playwright/test";

// R4 acceptance (DESIGN §13): search, dramatis personae, and settings — all working with the scriptorium
// API unreachable (the zero-online read path). We boot online once to pick a profile (GET /api/users),
// then abort every /api + /health request to simulate the server being down while keeping the Vite dev
// origin loadable (so the reader can reload). Fixture-mode reader; the features under test are all local.

const BOOK = "usr-ce8f5ebd29d0";

/** Read a file straight from OPFS in the page context. Null if absent. */
async function readOpfs(page: Page, path: string): Promise<string | null> {
  return page.evaluate(async (p) => {
    try {
      const parts = p.split("/");
      let dir = await navigator.storage.getDirectory();
      for (let i = 0; i < parts.length - 1; i += 1) dir = await dir.getDirectoryHandle(parts[i]);
      const fh = await dir.getFileHandle(parts[parts.length - 1]);
      return await (await fh.getFile()).text();
    } catch {
      return null;
    }
  }, path);
}

/** Simulate the scriptorium API being down: abort /api + /health, but let the app's own assets load. */
async function serverDown(context: BrowserContext): Promise<void> {
  await context.route(/\/(api|health)(\/|$)/, (route) => route.abort());
}

/** Land on the picker, choose Kris, wait for the reading surface. */
async function boot(page: Page): Promise<void> {
  await page.goto("/");
  await page.getByRole("button", { name: /Kris/ }).click();
  await expect(page.locator(".reader-progress")).toHaveText("1 / 6");
}

/** The dramatis-personae interstitial auto-opens on a fresh book; dismiss it to reach the reader bar. */
async function closeCastInterstitial(page: Page): Promise<void> {
  const cast = page.locator(".cast-page");
  await expect(cast).toBeVisible();
  await cast.getByRole("button", { name: "Done" }).click();
  await expect(cast).toHaveCount(0);
}

/** Turn pages until the reader shows `target / 6`. */
async function turnTo(page: Page, target: number): Promise<void> {
  for (let guard = 0; guard < 12; guard += 1) {
    const cur = parseInt((await page.locator(".reader-progress").innerText()).trim(), 10);
    if (cur === target) return;
    await page.getByRole("button", { name: cur < target ? "Next" : "Prev" }).click();
    await expect(page.locator(".reader-progress")).toHaveText(`${target} / 6`, { timeout: 2000 }).catch(() => {});
  }
  await expect(page.locator(".reader-progress")).toHaveText(`${target} / 6`);
}

test("search finds a phrase with the server down, jumps + flashes, and the index survives reload", async ({
  context,
  page,
}) => {
  await boot(page);
  await closeCastInterstitial(page);
  await serverDown(context);

  // Read forward, then search back to page 1 — a real cross-book jump.
  await turnTo(page, 4);
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await page.getByRole("searchbox").fill("harbour");
  const firstPage = page.locator(".search-result", { hasText: "p. 1" });
  await expect(firstPage.first()).toBeVisible();

  const buildCountAfterFirst = await page.evaluate(
    () => (window as unknown as { __searchBuildCount?: number }).__searchBuildCount,
  );
  expect(buildCountAfterFirst).toBeGreaterThanOrEqual(1); // built on first search
  expect(await readOpfs(page, `books/${BOOK}/search-index.json`)).not.toBeNull(); // persisted

  await firstPage.first().click();
  await expect(page.locator(".reader-progress")).toHaveText("1 / 6"); // jumped
  await expect(page.locator(".reader-scroll")).toHaveClass(/flash-page/); // match flash

  // Reload with the server still down: the persisted index must LOAD (no rebuild). Position on reload
  // is irrelevant here — we only care that search still works without rebuilding the index.
  await page.reload();
  await expect(page.locator(".reader-progress")).toHaveText(/^\d \/ 6$/);
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await page.getByRole("searchbox").fill("wanderer");
  await expect(page.locator(".search-result").first()).toBeVisible();
  const buildCountAfterReload = await page.evaluate(
    () => (window as unknown as { __searchBuildCount?: number }).__searchBuildCount,
  );
  expect(buildCountAfterReload ?? 0).toBe(0); // no build happened this page load → loaded from disk
});

test("dramatis personae auto-opens, filters to the introduced cast, and reopens from the toolbar", async ({
  context,
  page,
}) => {
  await boot(page);
  await serverDown(context);

  // The interstitial appears before chapter 1 and shows the character introduced on page 1.
  const cast = page.locator(".cast-page");
  await expect(cast).toBeVisible();
  await expect(cast.getByText("the Wanderer")).toBeVisible();
  await cast.getByRole("button", { name: "Done" }).click();
  await expect(cast).toHaveCount(0);

  // The toolbar Cast button reopens it.
  await page.getByRole("button", { name: "Cast", exact: true }).click();
  await expect(cast).toBeVisible();
  await expect(cast.getByText("the Wanderer")).toBeVisible();
});

test("theme + font-size changes persist across reload", async ({ context, page }) => {
  await boot(page);
  await closeCastInterstitial(page);
  await serverDown(context);

  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "Dark" }).click();
  await page.getByRole("button", { name: "Larger text" }).click();

  const themeBefore = await page.evaluate(() => document.documentElement.getAttribute("data-theme"));
  const scaleBefore = await page.evaluate(() =>
    document.documentElement.style.getPropertyValue("--reader-font-scale"),
  );
  expect(themeBefore).toBe("dark");
  expect(parseFloat(scaleBefore)).toBeGreaterThan(1);

  // Ensure both prefs are flushed to OPFS before reloading (writes are fire-and-forget).
  await expect
    .poll(async () => {
      const raw = await readOpfs(page, "settings/prefs.json");
      if (!raw) return null;
      const p = JSON.parse(raw) as { theme: string; fontStep: number };
      return `${p.theme}:${p.fontStep}`;
    })
    .toBe("dark:3");

  await page.reload();
  await expect(page.locator(".reader-progress")).toHaveText("1 / 6");
  const themeAfter = await page.evaluate(() => document.documentElement.getAttribute("data-theme"));
  const scaleAfter = await page.evaluate(() =>
    document.documentElement.style.getPropertyValue("--reader-font-scale"),
  );
  expect(themeAfter).toBe("dark");
  expect(scaleAfter).toBe(scaleBefore);
});
