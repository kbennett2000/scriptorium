import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { MemoryStorage } from "../shell";
import { DEFAULT_SET_ID, readActiveSet, writeActiveSet } from "./activeSet";
import { SetPicker } from "./SetPicker";

// Phase 1 of per-user picture sets (DESIGN §8, ADR-0014): the active-set persistence and the
// "Pictures" switcher. A set only changes which images show, never the text — and switching is
// fully offline (no network anywhere in this module).

describe("activeSet persistence", () => {
  it("defaults to 'default' when nothing is stored", async () => {
    const storage = new MemoryStorage();
    expect(await readActiveSet(storage, "kris", "pg-35")).toBe(DEFAULT_SET_ID);
  });

  it("round-trips a chosen set, namespaced per (user, book)", async () => {
    const storage = new MemoryStorage();
    await writeActiveSet(storage, "kris", "pg-35", "set-0a1b2c3d4e5f");
    expect(await readActiveSet(storage, "kris", "pg-35")).toBe("set-0a1b2c3d4e5f");
    // A different profile and a different book are unaffected (private + per-book).
    expect(await readActiveSet(storage, "amy", "pg-35")).toBe(DEFAULT_SET_ID);
    expect(await readActiveSet(storage, "kris", "pg-42")).toBe(DEFAULT_SET_ID);
  });

  it("falls back to 'default' on a corrupt stored value", async () => {
    const storage = new MemoryStorage();
    await storage.writeText("artsets-active/kris/pg-35.json", "{not json");
    expect(await readActiveSet(storage, "kris", "pg-35")).toBe(DEFAULT_SET_ID);
  });
});

describe("SetPicker", () => {
  const SETS = [
    { set_id: "default", kind: "default" as const, label: "Default", status: "ready" as const },
  ];

  it("lists the sets and marks the active one 'In use'", () => {
    render(
      <SetPicker sets={SETS} activeSetId="default" onChoose={() => {}} onClose={() => {}} />,
    );
    expect(screen.getByRole("dialog", { name: "Pictures" })).toBeInTheDocument();
    expect(screen.getByText("Default")).toBeInTheDocument();
    expect(screen.getByLabelText("In use")).toBeInTheDocument();
  });

  it("reports the chosen set and closes", async () => {
    const onChoose = vi.fn();
    const onClose = vi.fn();
    render(
      <SetPicker sets={SETS} activeSetId="default" onChoose={onChoose} onClose={onClose} />,
    );
    await userEvent.click(screen.getByRole("button", { name: /Default/ }));
    expect(onChoose).toHaveBeenCalledWith("default");
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(onClose).toHaveBeenCalled();
  });
});
