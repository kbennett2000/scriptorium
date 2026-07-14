import { expect, test, type Page } from "@playwright/test";

// R3 acceptance (DESIGN §12/§13): two isolated browser contexts = two devices sharing one household
// profile against a live server, edited offline, then synced. Asserts server-authoritative
// convergence (byte-equal docs), furthest-wins + current-LWW positions with the jump-to-furthest
// chip, later-modified-wins for a delete-vs-recolor conflict, and zero network on the reading path.
// Fixture-mode reader + Vite proxy (see playwright.config.ts); the sync engine/merge/picker are real.

const BOOK = "usr-ce8f5ebd29d0";
const ANN = `annotations/kris/${BOOK}.json`;
const POS = `positions/kris/${BOOK}.json`;

/** Read a file straight from OPFS in the page context — the true persisted bytes. Null if absent. */
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

/** Boot a context: land on the picker, choose Kris, open the fixture book. */
async function boot(page: Page): Promise<void> {
  await page.goto("/");
  await page.getByRole("button", { name: /Kris/ }).click();
  await expect(page.locator(".reader-progress")).toHaveText("1 / 6");
  // R4: the dramatis-personae interstitial auto-opens on a fresh book — dismiss it to reach the reader.
  const cast = page.locator(".cast-page");
  await expect(cast).toBeVisible();
  await cast.getByRole("button", { name: "Done" }).click();
  await expect(cast).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "The Winter Quay" })).toBeVisible();
}

/** Select a character range in the first paragraph and surface the selection bar. */
async function selectText(page: Page, start: number, end: number): Promise<void> {
  await page.evaluate(
    ({ s, e }) => {
      const para = document.querySelector(".page-para");
      const node = para?.firstChild;
      if (!node) throw new Error("no paragraph text");
      const range = document.createRange();
      range.setStart(node, s);
      range.setEnd(node, e);
      const sel = window.getSelection();
      sel?.removeAllRanges();
      sel?.addRange(range);
      document.dispatchEvent(new Event("selectionchange"));
    },
    { s: start, e: end },
  );
}

/** Turn pages (Next/Prev) until the reader shows `target / 6`. */
async function turnTo(page: Page, target: number): Promise<void> {
  for (let guard = 0; guard < 12; guard += 1) {
    const cur = parseInt((await page.locator(".reader-progress").innerText()).trim(), 10);
    if (cur === target) return;
    await page.getByRole("button", { name: cur < target ? "Next" : "Prev" }).click();
    await expect(page.locator(".reader-progress")).toHaveText(`${target} / 6`, { timeout: 2000 }).catch(() => {});
  }
  await expect(page.locator(".reader-progress")).toHaveText(`${target} / 6`);
}

/** Trigger a manual sync via the status badge and let the adopt-write settle. */
async function syncAndSettle(page: Page): Promise<void> {
  await Promise.all([
    page
      .waitForResponse((r) => r.url().includes("/api/sync/") && r.request().method() === "PUT", { timeout: 15_000 })
      .catch(() => {}),
    page.locator(".sync-badge").first().click(),
  ]);
  await page.waitForTimeout(300);
}

test("two devices converge; furthest-wins + current-LWW + jump chip; later-modified-wins", async ({
  browser,
}) => {
  const ctxA = await browser.newContext();
  const ctxB = await browser.newContext();
  const a = await ctxA.newPage();
  const b = await ctxB.newPage();
  await boot(a);
  await boot(b);

  // --- offline edits: A highlights + reads to p5, then (later) B notes + reads to p3 ---
  // The selection bar / hl-menu are absolutely-positioned overlays anchored to the selection rect,
  // which can fall outside Playwright's actionability viewport — dispatch the click event directly.
  await a.context().setOffline(true);
  await selectText(a, 0, 10);
  await a.getByRole("button", { name: "Highlight yellow" }).dispatchEvent("click");
  await expect(a.locator(".hl").first()).toBeVisible();
  await turnTo(a, 5);

  await b.context().setOffline(true);
  await selectText(b, 20, 35);
  await b.getByRole("button", { name: "Note" }).dispatchEvent("click");
  await b.locator(".note-input").fill("sync-note");
  await b.getByRole("button", { name: "Save" }).dispatchEvent("click");
  await expect(b.locator(".hl").first()).toBeVisible();
  await turnTo(b, 3);

  // --- back online; sync A, B, A so both adopt the full union ---
  await a.context().setOffline(false);
  await b.context().setOffline(false);
  await syncAndSettle(a);
  await syncAndSettle(b);
  await syncAndSettle(a);

  // Byte-equal annotation docs with both edits present.
  await expect
    .poll(
      async () => {
        const [ta, tb] = await Promise.all([readOpfs(a, ANN), readOpfs(b, ANN)]);
        if (!ta || !tb || ta !== tb) return -1;
        return (JSON.parse(ta).annotations as unknown[]).length;
      },
      { timeout: 15_000 },
    )
    .toBe(2);

  // Positions: furthest = p5 on both; B's current = p3 (later write wins).
  const posB = JSON.parse((await readOpfs(b, POS)) ?? "{}");
  const posA = JSON.parse((await readOpfs(a, POS)) ?? "{}");
  expect(posA.furthest.page_seq).toBe(5);
  expect(posB.furthest.page_seq).toBe(5);
  expect(posB.current.page_seq).toBe(3);

  // The jump-to-furthest chip is visible on B (its current p3 is behind the household furthest p5).
  await expect(b.getByRole("button", { name: /Jump to furthest/ })).toBeVisible();

  // --- LWW conflict: delete the shared highlight on A, recolor it (later) on B → recolor wins ---
  const highlightId = (JSON.parse((await readOpfs(a, ANN)) ?? "{}").annotations as { id: string; type: string }[]).find(
    (x) => x.type === "highlight",
  )!.id;

  await a.context().setOffline(true);
  await b.context().setOffline(true);

  await turnTo(a, 1);
  await a.locator(`[data-annot-id="${highlightId}"]`).first().click();
  await a.getByRole("button", { name: "Delete" }).dispatchEvent("click");
  await a.waitForTimeout(60); // ensure B's recolor carries a strictly later `modified`

  await turnTo(b, 1);
  await b.locator(`[data-annot-id="${highlightId}"]`).first().click();
  await b.getByRole("button", { name: "Recolor pink" }).dispatchEvent("click");

  await a.context().setOffline(false);
  await b.context().setOffline(false);
  await syncAndSettle(a);
  await syncAndSettle(b);
  await syncAndSettle(a);

  // Both converge to: highlight live (deletion lost), color pink (the later edit).
  await expect
    .poll(
      async () => {
        const [ta, tb] = await Promise.all([readOpfs(a, ANN), readOpfs(b, ANN)]);
        if (!ta || !tb || ta !== tb) return null;
        const h = (JSON.parse(ta).annotations as { id: string; deleted: boolean; color?: string }[]).find(
          (x) => x.id === highlightId,
        );
        return h && !h.deleted ? h.color : "deleted";
      },
      { timeout: 15_000 },
    )
    .toBe("pink");

  await ctxA.close();
  await ctxB.close();
});

test("reading-path page-turns issue no network requests", async ({ browser }) => {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await boot(page);
  await page.waitForTimeout(800); // let the mount/foreground sync settle first

  let apiCalls = 0;
  page.on("request", (r) => {
    if (r.url().includes("/api/")) apiCalls += 1;
  });

  for (let i = 0; i < 3; i += 1) {
    await page.getByRole("button", { name: "Next" }).click();
    await expect(page.locator(".reader-progress")).toHaveText(`${i + 2} / 6`);
  }

  expect(apiCalls).toBe(0);
  await ctx.close();
});
