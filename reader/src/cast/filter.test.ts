import { describe, expect, it } from "vitest";

import type { Cast } from "@scriptorium/shared";

import { visibleCharacters } from "./filter";

// The ADR-0008 no-spoilers cast filter — the named acceptance test: a character first mentioned on
// page 40 must be invisible while furthest-read is 30, and appear once the reader passes page 40.

function character(slug: string, mention_pages: string[]): Cast["characters"][number] {
  return {
    slug,
    name: slug,
    aliases: [],
    mention_pages,
    major: true,
    visual_description: null,
    one_line: "",
    tags: [],
    portrait: null,
    edited_by_human: false,
  };
}

const CAST: Cast = {
  characters: [
    character("narrator", ["0001"]),
    character("stranger", ["0040", "0041"]),
  ],
};

describe("visibleCharacters (ADR-0008)", () => {
  it("hides a character first mentioned on page 40 while furthest-read is 30", () => {
    const slugs = visibleCharacters(CAST, 30).map((c) => c.slug);
    expect(slugs).toEqual(["narrator"]);
    expect(slugs).not.toContain("stranger");
  });

  it("reveals that character once the reader reaches page 40", () => {
    expect(visibleCharacters(CAST, 40).map((c) => c.slug)).toEqual(["narrator", "stranger"]);
  });

  it("gates exactly at the mention page (39 hidden, 40 shown, 41 shown)", () => {
    expect(visibleCharacters(CAST, 39).map((c) => c.slug)).toEqual(["narrator"]);
    expect(visibleCharacters(CAST, 40).map((c) => c.slug)).toContain("stranger");
    expect(visibleCharacters(CAST, 41).map((c) => c.slug)).toContain("stranger");
  });

  it("preserves cast order among the visible characters", () => {
    expect(visibleCharacters(CAST, 100).map((c) => c.slug)).toEqual(["narrator", "stranger"]);
  });
});
