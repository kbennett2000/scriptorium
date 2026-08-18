import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { BundleReader } from "./BundleReader";
import { Plate } from "./Plate";

// ADR-0037: a plate that has an accepted clip shows a play button over the still; clicking it swaps
// in an inline <video>. Shape/behavior only — never the clip content. A plate without a clip shows
// just the still (no play button).

function readerWith(opts: {
  image: string | null;
  hasVideo?: boolean;
  video?: string | null;
}): BundleReader {
  return {
    readJson: vi.fn(),
    imageUrl: vi.fn(async () => opts.image),
    hasVideo: opts.hasVideo === undefined ? undefined : () => opts.hasVideo!,
    videoUrl: opts.video === undefined ? undefined : vi.fn(async () => opts.video ?? null),
    dispose: vi.fn(),
  };
}

describe("Plate", () => {
  const base = {
    relPath: "images/web/plates/0001.webp",
    plateId: "0001",
    alt: "Plate for page 1",
    onOpen: () => {},
  };

  it("shows no play button when the reader reports no video", async () => {
    const reader = readerWith({ image: "blob:still", hasVideo: false });
    render(<Plate reader={reader} {...base} />);
    await screen.findByAltText("Plate for page 1");
    expect(screen.queryByRole("button", { name: /play video/i })).toBeNull();
  });

  it("shows a play button and swaps to a <video> on click when a clip exists", async () => {
    const reader = readerWith({ image: "blob:still", hasVideo: true, video: "blob:clip" });
    const { container } = render(<Plate reader={reader} {...base} />);
    const play = await screen.findByRole("button", { name: /play video/i });

    expect(container.querySelector("video")).toBeNull(); // still first
    fireEvent.click(play);

    await waitFor(() => expect(container.querySelector("video")).not.toBeNull());
    expect(container.querySelector("video")?.getAttribute("src")).toBe("blob:clip");
    expect(reader.videoUrl).toHaveBeenCalledWith("0001");
  });
});
