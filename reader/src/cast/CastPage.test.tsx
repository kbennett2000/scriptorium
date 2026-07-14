import { describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import type { Cast } from "@scriptorium/shared";

import type { BundleReader } from "../readerview/BundleReader";
import { CastPage } from "./CastPage";

// The dramatis-personae overlay applies the ADR-0008 filter through the real component: a character
// first mentioned ahead of furthest-read is absent from the rendered list and appears once passed.

function character(slug: string, name: string, mention_pages: string[]): Cast["characters"][number] {
  return {
    slug,
    name,
    aliases: [],
    mention_pages,
    major: true,
    visual_description: null,
    one_line: `${name} one-liner`,
    tags: [],
    portrait: null,
    edited_by_human: false,
  };
}

const CAST: Cast = {
  characters: [
    character("narrator", "The Narrator", ["0001"]),
    character("harbourmaster", "The Harbourmaster", ["0006"]),
  ],
};

const stubReader: BundleReader = {
  async readJson<T>(): Promise<T> {
    throw new Error("unused");
  },
  async imageUrl() {
    return null; // no portrait thumbs → monogram fallback
  },
  dispose() {},
};

describe("CastPage (ADR-0008 in the overlay)", () => {
  it("hides a character mentioned only ahead of furthest-read", async () => {
    render(<CastPage reader={stubReader} cast={CAST} furthestSeq={1} onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText("The Narrator")).toBeInTheDocument());
    expect(screen.queryByText("The Harbourmaster")).not.toBeInTheDocument();
  });

  it("reveals that character once furthest-read reaches its page", async () => {
    render(<CastPage reader={stubReader} cast={CAST} furthestSeq={6} onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText("The Harbourmaster")).toBeInTheDocument());
    expect(screen.getByText("The Narrator")).toBeInTheDocument();
  });
});
