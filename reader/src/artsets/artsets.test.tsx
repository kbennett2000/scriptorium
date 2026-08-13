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
    {
      set_id: "default",
      kind: "default" as const,
      label: "Default",
      status: "ready" as const,
      residency: "resident" as const,
    },
  ];
  const noop = () => {};
  const base = {
    styles: [],
    models: [],
    online: true,
    busy: false,
    error: null,
    onChoose: noop,
    onCreate: noop,
    onDelete: noop,
    onRetry: noop,
    onClose: noop,
  };

  it("lists the sets and marks the active one 'In use'", () => {
    render(<SetPicker {...base} sets={SETS} activeSetId="default" />);
    expect(screen.getByRole("dialog", { name: "Pictures" })).toBeInTheDocument();
    expect(screen.getByText("Default")).toBeInTheDocument();
    expect(screen.getByText("✓ In use")).toBeInTheDocument();
  });

  it("reports the chosen set", async () => {
    const onChoose = vi.fn();
    render(<SetPicker {...base} sets={SETS} activeSetId="default" onChoose={onChoose} />);
    await userEvent.click(screen.getByRole("button", { name: /Default/ }));
    expect(onChoose).toHaveBeenCalledWith("default");
  });

  it("closes on Done", async () => {
    const onClose = vi.fn();
    render(<SetPicker {...base} sets={SETS} activeSetId="default" onClose={onClose} />);
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("shows a live count and a progress bar while a set is generating", () => {
    const sets = [
      ...SETS,
      {
        set_id: "set-0a1b2c3d4e5f",
        kind: "style" as const,
        label: "Comic Book",
        status: "generating" as const,
        residency: "available" as const,
        render_progress: { done: 3, total: 8 },
      },
    ];
    render(<SetPicker {...base} sets={sets} activeSetId="default" />);
    expect(screen.getByText("Making your pictures… 3 of 8")).toBeInTheDocument();
    const bar = screen.getByRole("progressbar", { name: "Making Comic Book" });
    expect(bar).toHaveAttribute("value", "3");
    expect(bar).toHaveAttribute("max", "8");
  });

  it("offers Retry on a failed set and reports it", async () => {
    const onRetry = vi.fn();
    const sets = [
      ...SETS,
      {
        set_id: "set-aaaabbbbcccc",
        kind: "style" as const,
        label: "Comic Book",
        status: "failed" as const,
        residency: "available" as const,
      },
    ];
    render(<SetPicker {...base} sets={sets} activeSetId="default" onRetry={onRetry} />);
    expect(screen.getByText("Couldn’t make this one")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry Comic Book" }));
    expect(onRetry).toHaveBeenCalledWith("set-aaaabbbbcccc");
  });
});
