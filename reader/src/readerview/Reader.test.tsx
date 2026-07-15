import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Page as PageDoc, Selection, Structure } from "@scriptorium/shared";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MemoryStorage } from "../shell";
import type { BundleReader } from "./BundleReader";
import { Reader } from "./Reader";

// The reading surface, driven by an injected fake BundleReader (the component is source-agnostic by
// design). Covers: chapter header on a chapter-open page, byte-faithful paragraph count, retired-plate
// filtering, navigation, "never touch images/plates/*.png", and local position persist/restore.

const BOOK = "usr-reader00000";

const STRUCTURE: Structure = {
  chapters: [{ index: 1, title: "The Winter Quay", page_ids: ["0001", "0002"] }],
};

const SELECTION: Selection = {
  preset: "classic",
  params: { min_gap: 2, max_gap: 6, salience_floor: 0.55, chapter_open: true, scene_boundary: true },
  plates: [
    { page_id: "0001", reason: "chapter_open", salience: 0.4, status: "rendered", added_in_revision: 1 },
    // A RETIRED plate on page 2 — its files may remain but it must not render.
    { page_id: "0002", reason: "fill", salience: 0.7, status: "retired", added_in_revision: 1 },
  ],
};

const PAGES: Record<string, PageDoc> = {
  "0001": { id: "0001", seq: 1, chapter: 1, text: "Para one.\n\nPara two.\n\nPara three.", word_count: 6 },
  "0002": { id: "0002", seq: 2, chapter: 1, text: "Second page.\n\nAnother paragraph.", word_count: 4 },
};

/** An in-memory BundleReader that records which image paths were requested. */
function makeFakeReader() {
  const requestedImages: string[] = [];
  const reader: BundleReader = {
    async readJson<T>(relPath: string): Promise<T> {
      if (relPath === "structure.json") return STRUCTURE as T;
      if (relPath === "selection.json") return SELECTION as T;
      const m = /^pages\/(\d+)\.json$/.exec(relPath);
      if (m && PAGES[m[1]]) return PAGES[m[1]] as T;
      throw new Error(`unexpected readJson: ${relPath}`);
    },
    async imageUrl(relPath: string): Promise<string | null> {
      requestedImages.push(relPath);
      return relPath === "images/web/plates/0001.webp" ? "blob:fake-plate" : null;
    },
    dispose: vi.fn(),
  };
  return { reader, requestedImages };
}

function paraCount(container: HTMLElement): number {
  return container.querySelectorAll(".page-para").length;
}

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => "blob:x");
  URL.revokeObjectURL = vi.fn();
});
afterEach(() => {
  window.location.hash = "";
  vi.restoreAllMocks();
});

describe("Reader", () => {
  it("renders a chapter-open page: title header, plate, byte-faithful paragraphs", async () => {
    const { reader } = makeFakeReader();
    const { container } = render(
      <Reader reader={reader} storage={new MemoryStorage()} bookId={BOOK} onExit={() => {}} />,
    );
    expect(await screen.findByText("The Winter Quay")).toBeInTheDocument();
    expect(await screen.findByAltText("Plate for page 1")).toBeInTheDocument();
    await waitFor(() => expect(paraCount(container)).toBe(3));
    expect(screen.getByText("1 / 2")).toBeInTheDocument();
  });

  it("navigates to the next page: no header, retired plate hidden, new paragraphs", async () => {
    const { reader } = makeFakeReader();
    const { container } = render(
      <Reader reader={reader} storage={new MemoryStorage()} bookId={BOOK} onExit={() => {}} />,
    );
    await screen.findByText("The Winter Quay");
    await userEvent.click(screen.getByRole("button", { name: "Next" }));

    await waitFor(() => expect(screen.getByText("2 / 2")).toBeInTheDocument());
    expect(screen.queryByText("The Winter Quay")).not.toBeInTheDocument(); // page 2 isn't chapter-open
    expect(screen.queryByAltText("Plate for page 2")).not.toBeInTheDocument(); // retired → hidden
    expect(paraCount(container)).toBe(2);
  });

  it("turns pages with ← / → keys", async () => {
    const { reader } = makeFakeReader();
    render(<Reader reader={reader} storage={new MemoryStorage()} bookId={BOOK} onExit={() => {}} />);
    await screen.findByText("The Winter Quay");
    await userEvent.keyboard("{ArrowRight}");
    await waitFor(() => expect(screen.getByText("2 / 2")).toBeInTheDocument());
    await userEvent.keyboard("{ArrowLeft}");
    await waitFor(() => expect(screen.getByText("1 / 2")).toBeInTheDocument());
  });

  it("only ever requests reader web images, never the .png originals", async () => {
    const { reader, requestedImages } = makeFakeReader();
    render(<Reader reader={reader} storage={new MemoryStorage()} bookId={BOOK} onExit={() => {}} />);
    await screen.findByAltText("Plate for page 1");
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText("2 / 2");
    expect(requestedImages.length).toBeGreaterThan(0);
    for (const p of requestedImages) {
      expect(p.startsWith("images/web/")).toBe(true);
      expect(p.endsWith(".png")).toBe(false);
    }
  });

  it("persists position on page-turn and restores it on reopen", async () => {
    const storage = new MemoryStorage();
    const first = makeFakeReader();
    const { unmount } = render(
      <Reader reader={first.reader} storage={storage} bookId={BOOK} onExit={() => {}} />,
    );
    await screen.findByText("The Winter Quay");
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(screen.getByText("2 / 2")).toBeInTheDocument());
    // Give the post-render persist effect a tick to flush to storage.
    await waitFor(async () =>
      expect(await storage.exists(`positions/default/${BOOK}.json`)).toBe(true),
    );
    unmount();

    const second = makeFakeReader();
    render(<Reader reader={second.reader} storage={storage} bookId={BOOK} onExit={() => {}} />);
    // Reopened at the saved current position (page 2), not back at page 1.
    await waitFor(() => expect(screen.getByText("2 / 2")).toBeInTheDocument());
  });

  it("opens a Pictures menu showing the Default set", async () => {
    const { reader } = makeFakeReader();
    render(<Reader reader={reader} storage={new MemoryStorage()} bookId={BOOK} onExit={() => {}} />);
    await screen.findByText("The Winter Quay");
    await userEvent.click(screen.getByRole("button", { name: "Pictures" }));
    const dialog = await screen.findByRole("dialog", { name: "Pictures" });
    expect(within(dialog).getByText("Default")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("In use")).toBeInTheDocument();
  });
});

describe("Reader — pictures per scene (multiple plates on a page)", () => {
  // Page 0001 has 3 paragraphs; anchors: "Para one."=9 +2 => para 2 at 11; +"Para two."(9)+2 => para 3 at 22.
  const MULTI: Selection = {
    preset: "lavish",
    params: { min_gap: 1, max_gap: 3, salience_floor: 0.4, chapter_open: true, scene_boundary: true },
    plates: [
      { page_id: "0001", reason: "chapter_open", salience: 0.5, status: "rendered", added_in_revision: 1 },
      { page_id: "0001", plate_id: "0001-2", anchor: 11, segment_index: 1, reason: "segment", salience: 0.5, status: "rendered", added_in_revision: 1 },
      { page_id: "0001", plate_id: "0001-3", anchor: 22, segment_index: 2, reason: "segment", salience: 0.5, status: "rendered", added_in_revision: 1 },
    ],
  };

  function makeMultiReader() {
    const requestedImages: string[] = [];
    const reader: BundleReader = {
      async readJson<T>(relPath: string): Promise<T> {
        if (relPath === "structure.json") return STRUCTURE as T;
        if (relPath === "selection.json") return MULTI as T;
        const m = /^pages\/(\d+)\.json$/.exec(relPath);
        if (m && PAGES[m[1]]) return PAGES[m[1]] as T;
        throw new Error(`unexpected readJson: ${relPath}`);
      },
      async imageUrl(relPath: string): Promise<string | null> {
        requestedImages.push(relPath);
        return /^images\/web\/plates\/0001(-\d+)?\.webp$/.test(relPath) ? `blob:${relPath}` : null;
      },
      dispose: vi.fn(),
    };
    return { reader, requestedImages };
  }

  beforeEach(() => {
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
  });

  it("renders all three plates in reading order, woven between paragraphs", async () => {
    const { reader } = makeMultiReader();
    const { container } = render(
      <Reader reader={reader} storage={new MemoryStorage()} bookId={BOOK} onExit={() => {}} />,
    );
    // All three illustrations render (distinguishable alts), and the text is intact.
    expect(await screen.findByAltText("Plate 1 for page 1")).toBeInTheDocument();
    expect(screen.getByAltText("Plate 2 for page 1")).toBeInTheDocument();
    expect(screen.getByAltText("Plate 3 for page 1")).toBeInTheDocument();
    await waitFor(() => expect(container.querySelectorAll(".page-para").length).toBe(3));

    // Document order: base image, then para 1, then image 2, para 2, image 3, para 3.
    const marks = Array.from(container.querySelectorAll("img, .page-para")).map((el) =>
      el.tagName === "IMG" ? (el as HTMLImageElement).alt : "PARA",
    );
    expect(marks).toEqual([
      "Plate 1 for page 1", "PARA", "Plate 2 for page 1", "PARA", "Plate 3 for page 1", "PARA",
    ]);
  });

  it("adds no network paths outside images/web when a page has several plates", async () => {
    const { reader, requestedImages } = makeMultiReader();
    render(<Reader reader={reader} storage={new MemoryStorage()} bookId={BOOK} onExit={() => {}} />);
    await screen.findByAltText("Plate 1 for page 1");
    for (const p of requestedImages) {
      expect(p.startsWith("images/web/")).toBe(true);
      expect(p.endsWith(".png")).toBe(false);
    }
  });
});
