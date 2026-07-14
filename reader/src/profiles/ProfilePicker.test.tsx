import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Annotations, Positions, Users } from "@scriptorium/shared";

import { MemoryStorage } from "../shell";
import type { SyncClient } from "../sync";
import { ProfilePicker } from "./ProfilePicker";
import { readUsersCache } from "./activeProfile";

const USERS: Users = [
  { id: "kris", name: "Kris", color: "#e07a5f" },
  { id: "amy", name: "Amy", color: "#3d405b" },
];

function fakeClient(over: Partial<SyncClient> = {}): SyncClient {
  return {
    reachable: async () => true,
    fetchUsers: async () => USERS,
    getAnnotations: async (u, b): Promise<Annotations> => ({ book_id: b, user_id: u, annotations: [] }),
    putAnnotations: async (_u, _b, d) => d,
    getPositions: async (): Promise<Positions | null> => null,
    putPositions: async (_u, _b, d) => d,
    ...over,
  };
}

describe("ProfilePicker", () => {
  it("lists profiles, calls onPick, and caches the roster", async () => {
    const storage = new MemoryStorage();
    const onPick = vi.fn();
    render(<ProfilePicker client={fakeClient()} storage={storage} onPick={onPick} />);

    await screen.findByText("Kris");
    expect(screen.getByText("Amy")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Kris/ }));
    expect(onPick).toHaveBeenCalledWith("kris");
    await waitFor(async () => expect(await readUsersCache(storage)).toEqual(USERS));
  });

  it("falls back to the cached roster when the server is unreachable", async () => {
    const storage = new MemoryStorage();
    await storage.writeText("users-cache.json", JSON.stringify(USERS));
    const client = fakeClient({
      fetchUsers: async () => {
        throw new Error("offline");
      },
    });
    render(<ProfilePicker client={client} storage={storage} onPick={vi.fn()} />);
    await screen.findByText("Kris");
  });

  it("shows a retry when there is no server and no cache", async () => {
    const storage = new MemoryStorage();
    const client = fakeClient({
      fetchUsers: async () => {
        throw new Error("offline");
      },
    });
    render(<ProfilePicker client={client} storage={storage} onPick={vi.fn()} />);
    await screen.findByRole("button", { name: "Retry" });
  });
});
