import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { App } from "../App";

// Smoke of the cast-review gate (ADR-0032) with a fully stubbed backend: detail at cast_done →
// Review cast → edit a description → approve cast → back on detail, now cast_approved. The cast
// screen reuses the review payload endpoint, which returns cast-only (empty plates) before P5.

const BOOK_ID = "usr-castgate";

function job(state: string) {
  return {
    id: BOOK_ID, book_id: BOOK_ID, state, source: {}, bake_config: {},
    title: "Cast Gate Book", warnings: [], prompt_warnings: {}, render_stub: false,
    failed_units: [], prev_state: null, started: true,
    created_at: "2026-08-13T00:00:00Z", updated_at: "2026-08-13T00:00:00Z",
  };
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status, headers: { "Content-Type": "application/json" },
  });
}

function installFetch(state: { bookState: string; edited: boolean }) {
  const handler = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = new URL(typeof input === "string" ? input : input.toString(), "http://localhost");
    const path = url.pathname;
    const method = (init?.method ?? "GET").toUpperCase();

    if (method === "GET" && path === "/api/admin/gpu") {
      return json({
        gpu: { present: true, util_percent: 20, mem_used_mib: 3000, mem_total_mib: 12227 },
        text_model: { loaded: true, name: "qwen3.5:9b", processor: "gpu" },
        summary: "gpu",
      });
    }
    if (method === "GET" && path === `/api/admin/books/${BOOK_ID}`) {
      return json(job(state.bookState));
    }
    if (method === "GET" && path === `/api/admin/books/${BOOK_ID}/review`) {
      // Cast-only payload: selection/prompts empty before P5 (ADR-0032 tolerant GET).
      return json({
        book_id: BOOK_ID,
        state: state.bookState,
        selection: { plates: [] },
        cast: {
          characters: [
            {
              slug: "the-keeper", name: "the Keeper", aliases: [], mention_pages: ["0001"],
              major: true, visual_description: "a stooped lamplighter",
              one_line: "Tends the lamp.", tags: [], portrait: null,
              edited_by_human: state.edited,
            },
          ],
        },
        prompts: [],
        warnings: [], prompt_warnings: {}, failed_units: [], beats: {},
        render_stub: false, portrait_anchor_counts: {}, portrait_rendered: {},
      });
    }
    if (method === "PUT" && path === `/api/admin/books/${BOOK_ID}/review/cast/the-keeper`) {
      state.edited = true;
      return json({
        slug: "the-keeper", name: "the Keeper", aliases: [], mention_pages: ["0001"],
        major: true, visual_description: "a wiry old keeper", one_line: "Tends the lamp.",
        tags: [], portrait: null, edited_by_human: true,
      });
    }
    if (method === "POST" && path === `/api/admin/books/${BOOK_ID}/approve-cast`) {
      state.bookState = "cast_approved";
      return json(job(state.bookState));
    }
    throw new Error(`unmocked ${method} ${path}`);
  };
  vi.stubGlobal("fetch", vi.fn(handler));
}

describe("cast-review gate", () => {
  beforeEach(() => {
    window.location.hash = `#/book/${BOOK_ID}`;
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("detail → Review cast → edit description → approve cast", async () => {
    const state = { bookState: "cast_done", edited: false };
    installFetch(state);
    const user = userEvent.setup();
    render(<App />);

    // Detail at the cast gate offers "Review cast" and shows the gate milestone.
    const reviewCast = await screen.findByRole("button", { name: /Review cast/i });
    expect(screen.getByText(/Cast approved \(review gate\)/)).toBeInTheDocument();
    await user.click(reviewCast);

    // Cast screen renders the one character and no plate table.
    expect(await screen.findByText("Cast (1)")).toBeInTheDocument();
    expect(screen.queryByText(/Plates \(/)).not.toBeInTheDocument();

    // Edit the description → "edited" badge appears.
    const descBox = screen.getByLabelText(/visual description/i);
    await user.clear(descBox);
    await user.type(descBox, "a wiry old keeper");
    await user.click(screen.getByRole("button", { name: /^Save$/ }));
    expect(await screen.findByText("edited")).toBeInTheDocument();

    // Approve cast → confirm → back on detail, now cast_approved.
    await user.click(screen.getByRole("button", { name: /Approve…/ }));
    const dialogText = await screen.findByText(/scene descriptions will be generated/i);
    const dialog = within(dialogText.closest(".dialog") as HTMLElement);
    await user.click(dialog.getByRole("button", { name: /Approve cast/i }));

    await waitFor(() => expect(screen.getAllByText("cast_approved").length).toBeGreaterThan(0));
  });
});
