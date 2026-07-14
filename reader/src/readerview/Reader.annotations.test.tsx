import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Page as PageDoc, Selection, Structure } from "@scriptorium/shared";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { readAnnotations } from "../annotations";
import { MemoryStorage } from "../shell";
import type { BundleReader } from "./BundleReader";
import { Reader } from "./Reader";

// R2 annotation surface behaviour through the real component (injected fake BundleReader + MemoryStorage):
// bookmark persist/restore across remount, a highlight surviving reload and rendering over the same
// characters, and a live selection blocking page-turns. The exhaustive anchor math lives in
// annotations/anchors.test.ts; here we prove the wiring and persistence.

const BOOK = "usr-annotest0001";

const STRUCTURE: Structure = {
  chapters: [{ index: 1, title: "The Winter Quay", page_ids: ["0001", "0002"] }],
};
const SELECTION: Selection = {
  preset: "classic",
  params: { min_gap: 2, max_gap: 6, salience_floor: 0.55, chapter_open: true, scene_boundary: true },
  plates: [],
};
const PAGES: Record<string, PageDoc> = {
  "0001": { id: "0001", seq: 1, chapter: 1, text: "Alpha beta gamma.\n\nDelta epsilon zeta.", word_count: 6 },
  "0002": { id: "0002", seq: 2, chapter: 1, text: "Second page here.", word_count: 3 },
};

function makeFakeReader(): BundleReader {
  return {
    async readJson<T>(relPath: string): Promise<T> {
      if (relPath === "structure.json") return STRUCTURE as T;
      if (relPath === "selection.json") return SELECTION as T;
      const m = /^pages\/(\d+)\.json$/.exec(relPath);
      if (m && PAGES[m[1]]) return PAGES[m[1]] as T;
      throw new Error(`unexpected readJson: ${relPath}`);
    },
    async imageUrl(): Promise<string | null> {
      return null;
    },
    dispose: vi.fn(),
  };
}

/** Select DOM text [start,end) within the first `.page-para` (jsdom-friendly: real Range + Selection). */
function selectInFirstParagraph(container: HTMLElement, start: number, end: number) {
  const para = container.querySelector<HTMLElement>(".page-para");
  const node = para?.firstChild as Text;
  const range = document.createRange();
  range.setStart(node, start);
  range.setEnd(node, end);
  const sel = window.getSelection();
  sel?.removeAllRanges();
  sel?.addRange(range);
  document.dispatchEvent(new Event("selectionchange"));
}

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => "blob:x");
  URL.revokeObjectURL = vi.fn();
});
afterEach(() => {
  window.location.hash = "";
  window.getSelection()?.removeAllRanges();
  vi.restoreAllMocks();
});

describe("Reader annotations", () => {
  it("toggles a bookmark that persists to storage and restores on remount", async () => {
    const storage = new MemoryStorage();
    const { unmount } = render(
      <Reader reader={makeFakeReader()} storage={storage} bookId={BOOK} onExit={() => {}} />,
    );
    await screen.findByText("The Winter Quay");

    await userEvent.click(screen.getByRole("button", { name: "Add bookmark" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Remove bookmark" })).toBeInTheDocument());

    // It reached storage in the wire shape.
    await waitFor(async () => {
      const doc = await readAnnotations(storage, BOOK);
      expect(doc.annotations.filter((a) => a.type === "bookmark" && !a.deleted)).toHaveLength(1);
    });
    unmount();

    render(<Reader reader={makeFakeReader()} storage={storage} bookId={BOOK} onExit={() => {}} />);
    // Remounted on page 1 → the bookmark shows as set.
    await waitFor(() => expect(screen.getByRole("button", { name: "Remove bookmark" })).toBeInTheDocument());
  });

  it("creates a highlight that survives reload and renders over the same characters", async () => {
    const storage = new MemoryStorage();
    const { container, unmount } = render(
      <Reader reader={makeFakeReader()} storage={storage} bookId={BOOK} onExit={() => {}} />,
    );
    await screen.findByText(/Alpha beta gamma/);

    // Select "beta" (chars 6..10 of "Alpha beta gamma.") and highlight it yellow.
    selectInFirstParagraph(container, 6, 10);
    const bar = await screen.findByRole("toolbar", { name: "Selection actions" });
    await userEvent.click(within(bar).getByRole("button", { name: "Highlight yellow" }));

    // A highlight span now wraps exactly "beta".
    await waitFor(() => {
      const span = container.querySelector<HTMLElement>("span.hl.hl-yellow");
      expect(span?.textContent).toBe("beta");
    });
    // Persisted.
    const doc = await readAnnotations(storage, BOOK);
    expect(doc.annotations).toHaveLength(1);
    expect(doc.annotations[0].anchor).toEqual({ start: 6, end: 10 });
    unmount();

    // Reload from the same storage → the highlight re-renders over the same characters.
    const second = render(
      <Reader reader={makeFakeReader()} storage={storage} bookId={BOOK} onExit={() => {}} />,
    );
    await screen.findByText(/Alpha/);
    await waitFor(() => {
      const span = second.container.querySelector<HTMLElement>("span.hl.hl-yellow");
      expect(span?.textContent).toBe("beta");
    });
  });

  it("does not turn the page while a text selection is live", async () => {
    const storage = new MemoryStorage();
    const { container } = render(
      <Reader reader={makeFakeReader()} storage={storage} bookId={BOOK} onExit={() => {}} />,
    );
    await screen.findByText(/Alpha beta gamma/);
    expect(screen.getByText("1 / 2")).toBeInTheDocument();

    selectInFirstParagraph(container, 0, 5); // "Alpha"
    await userEvent.keyboard("{ArrowRight}");
    // Still on page 1 — the live selection blocked the turn.
    expect(screen.getByText("1 / 2")).toBeInTheDocument();
  });
});
