import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { App } from "../App";

// End-to-end smoke of the operator flow with a fully stubbed backend (offline, no server): wizard →
// create → detail (phases progress) → review → edit a prompt → toggle a plate → approve. Asserts the
// UI reflects each step. This is the automated half of S9 acceptance box #1; the human browser walk
// (with a real server) is the other half.

const BOOK_ID = "usr-smoke01";

interface MockState {
  bookState: string;
  selectionPlates: {
    page_id: string;
    reason: string;
    salience: number;
    status: string;
    added_in_revision: number;
  }[];
  prompts: {
    page_id: string;
    derived: Record<string, unknown>;
    edited_prompt: string | null;
    final_subject_prompt: string;
  }[];
}

function freshState(): MockState {
  return {
    bookState: "prompts_draft",
    selectionPlates: [
      { page_id: "0001", reason: "chapter_open", salience: 0.71, status: "selected", added_in_revision: 1 },
      { page_id: "0002", reason: "fill", salience: 0.6, status: "selected", added_in_revision: 1 },
    ],
    prompts: [
      { page_id: "0001", derived: {}, edited_prompt: null, final_subject_prompt: "A clockmaker at his bench" },
      { page_id: "0002", derived: {}, edited_prompt: null, final_subject_prompt: "A rainy street at dusk" },
      { page_id: "cover", derived: {}, edited_prompt: null, final_subject_prompt: "Cover: the great clock" },
    ],
  };
}

function job(state: MockState) {
  return {
    id: BOOK_ID,
    book_id: BOOK_ID,
    state: state.bookState,
    source: {},
    bake_config: {},
    title: "Smoke Book",
    warnings: [],
    prompt_warnings: {},
    render_stub: false,
    failed_units: [],
    prev_state: null,
    started: true,
    created_at: "2026-07-13T00:00:00Z",
    updated_at: "2026-07-13T00:00:00Z",
  };
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function installFetch(state: MockState) {
  const handler = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = new URL(typeof input === "string" ? input : input.toString(), "http://localhost");
    const path = url.pathname;
    const method = (init?.method ?? "GET").toUpperCase();
    const body = init?.body ? JSON.parse(init.body as string) : undefined;

    if (method === "GET" && path === "/api/admin/styles") {
      return json({
        styles: [
          {
            id: "engraving",
            name: "Engraving",
            consistency_friendly: true,
            prefix: "",
            suffix: "",
            negative: "",
            portrait_prefix: "",
            params: { steps: null, cfg: null },
          },
        ],
      });
    }
    if (method === "GET" && path === "/api/admin/books") {
      return json({ books: [] });
    }
    if (method === "POST" && path === "/api/admin/books") {
      return json({ book_id: BOOK_ID, state: "ingested", warnings: [] });
    }
    if (method === "GET" && path === `/api/admin/books/${BOOK_ID}`) {
      return json(job(state));
    }
    if (method === "GET" && path === `/api/admin/books/${BOOK_ID}/review`) {
      return json({
        book_id: BOOK_ID,
        state: state.bookState,
        selection: { preset: "classic", params: {}, plates: state.selectionPlates },
        cast: {
          characters: [
            {
              slug: "the-clockmaker",
              name: "The Clockmaker",
              aliases: [],
              mention_pages: ["0001"],
              major: true,
              visual_description: "an old man",
              one_line: "keeps the town clock",
              tags: [],
              portrait: null,
              edited_by_human: false,
            },
          ],
        },
        prompts: state.prompts,
        warnings: [],
        prompt_warnings: {},
        failed_units: [],
        beats: { "0001": "He winds the great clock." },
      });
    }
    if (method === "PUT" && path.startsWith(`/api/admin/books/${BOOK_ID}/review/prompt/`)) {
      const pageId = path.split("/").pop()!;
      const prompt = state.prompts.find((p) => p.page_id === pageId)!;
      prompt.edited_prompt = body.edited_prompt;
      prompt.final_subject_prompt = body.edited_prompt ?? "reverted";
      return json(prompt);
    }
    if (method === "PUT" && path === `/api/admin/books/${BOOK_ID}/review/selection`) {
      for (const id of body.remove ?? []) {
        state.selectionPlates = state.selectionPlates.filter((p) => p.page_id !== id);
      }
      return json({ preset: "classic", params: {}, plates: state.selectionPlates });
    }
    if (method === "POST" && path === `/api/admin/books/${BOOK_ID}/approve`) {
      state.bookState = "approved";
      return json(job(state));
    }
    throw new Error(`unmocked ${method} ${path}`);
  };
  vi.stubGlobal("fetch", vi.fn(handler));
}

describe("admin workbench smoke", () => {
  beforeEach(() => {
    window.location.hash = "#/new";
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("walks wizard → detail → review → edit → toggle → approve", async () => {
    const state = freshState();
    installFetch(state);
    const user = userEvent.setup();
    render(<App />);

    // --- Wizard: styles load, paste a source, create. ---
    expect(await screen.findByText("Engraving")).toBeInTheDocument();
    await user.type(screen.getByLabelText("source text"), "# Chapter I\n\nOnce upon a time.");
    const createBtn = screen.getByRole("button", { name: /Create book/i });
    await waitFor(() => expect(createBtn).toBeEnabled());
    await user.click(createBtn);

    // --- Detail: phases progress + Open Review. ---
    const openReview = await screen.findByRole("button", { name: /Open Review/i });
    expect(screen.getByText(/Prompts \(P5\)/)).toBeInTheDocument();
    await user.click(openReview);

    // --- Review: two plates. ---
    expect(await screen.findByText("Plates (2)")).toBeInTheDocument();

    // Edit the 0001 prompt → an "edited" badge appears.
    const promptBox = screen.getByLabelText("prompt 0001");
    await user.clear(promptBox);
    await user.type(promptBox, "A clockmaker, hand-edited");
    // The plate's Save button (first Save in the table region).
    const saveButtons = screen.getAllByRole("button", { name: /^Save$/ });
    await user.click(saveButtons[0]);
    expect(await screen.findAllByText("edited")).toHaveLength(1);

    // Toggle plate 0002 off → count drops to 1.
    await user.click(screen.getByLabelText("include 0002"));
    expect(await screen.findByText("Plates (1)")).toBeInTheDocument();

    // --- Approve: confirmation shows the plate count, then locks. ---
    await user.click(screen.getByRole("button", { name: /Approve…/ }));
    const dialogText = await screen.findByText(/will be locked and queued/);
    const dialog = within(dialogText.closest(".dialog") as HTMLElement);
    // Confirmation names the renderable plate count (1 page plate after the toggle).
    const confirmBtn = dialog.getByRole("button", { name: /Approve 1 plates/ });
    expect(confirmBtn).toBeInTheDocument();
    await user.click(confirmBtn);

    // Back on detail, now approved.
    await waitFor(() => expect(screen.getAllByText("approved").length).toBeGreaterThan(0));
  });
});
