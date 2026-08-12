import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Artset, ArtsetList, Manifest } from "@scriptorium/shared";

import { MemoryStorage } from "../shell/memory";
import type { ArtsetApi, ArtsetClient, CreateSetBody, StyleOption } from "../shelf";
import { sha256Hex } from "../shelf/checkout";
import { readActiveSet } from "./activeSet";
import { SetPicker } from "./SetPicker";
import { useArtsets } from "./useArtsets";

// Phase 4 (ADR-0014): the "Pictures" menu wired to useArtsets — make → poll → download → switch,
// delete, and offline fallback. Behaviour/shape only, never image content. The image-source swap
// itself is proven in SetImageBundleReader.test; here we drive the menu's data flow.

const USER = "kris";
const BOOK = "usr-000000000000";
const NEW_SET = "set-aaaaaaaaaaaa";
const STYLES: StyleOption[] = [
  { id: "engraving", name: "Victorian Engraving", consistency_friendly: true },
];

type Summary = ArtsetList["sets"][number];

// A fake server: a mutable set map (so a set can flip generating → ready between polls) + a catalog.
class FakeApi implements ArtsetApi {
  sets = new Map<string, Summary>([
    ["default", { set_id: "default", kind: "default", label: "Default", status: "ready" }],
  ]);
  createCalls: CreateSetBody[] = [];
  deleteCalls: string[] = [];
  offline = false;

  async fetchSetList(user: string, book: string): Promise<ArtsetList> {
    if (this.offline) throw new Error("offline");
    return { book_id: book, user_id: user, active_set_id: "default", sets: [...this.sets.values()] };
  }
  async createSet(user: string, book: string, body: CreateSetBody): Promise<Artset> {
    this.createCalls.push(body);
    const s: Summary = {
      set_id: NEW_SET,
      kind: body.kind,
      label: body.style_id ?? "Re-roll",
      style_id: body.style_id,
      status: "generating",
    };
    this.sets.set(NEW_SET, s);
    return { ...s, book_id: book, user_id: user, created: "2026-07-14T00:00:00Z" } as Artset;
  }
  async deleteSet(_user: string, _book: string, setId: string): Promise<void> {
    this.deleteCalls.push(setId);
    this.sets.delete(setId);
  }
  async fetchStyles(): Promise<StyleOption[]> {
    return STYLES;
  }
  markReady(setId: string) {
    const s = this.sets.get(setId);
    if (s) s.status = "ready";
  }
}

// A fake download source: one web image whose manifest hashes match, so artsetCheckout verifies.
class FakeDownload implements ArtsetClient {
  private bytes = new Map<string, Uint8Array>([["images/web/cover.webp", new Uint8Array([1, 2, 3, 4])]]);
  manifest!: Manifest;
  async init() {
    const files: Manifest["files"] = [];
    for (const [path, b] of this.bytes) files.push({ path, sha256: await sha256Hex(b), bytes: b.length });
    this.manifest = {
      book_id: BOOK,
      revision: 1,
      bundle_version: 1,
      content_fingerprint: "0".repeat(64),
      files,
      reader_required: ["images/web/**"],
      total_bytes_reader: files.reduce((s, f) => s + f.bytes, 0),
    };
  }
  async fetchSetManifest(): Promise<Manifest> {
    return this.manifest;
  }
  async fetchSetFileBytes(_u: string, _b: string, _s: string, path: string): Promise<Uint8Array> {
    return this.bytes.get(path)!;
  }
}

function Harness({ api, download, storage }: { api: ArtsetApi; download: ArtsetClient; storage: MemoryStorage }) {
  const a = useArtsets(api, download, storage, USER, BOOK, true, 5);
  return (
    <SetPicker
      sets={a.sets}
      styles={a.styles}
      activeSetId={a.activeSetId}
      online={a.online}
      busy={a.busy}
      error={a.error}
      onChoose={a.choose}
      onCreate={a.create}
      onDelete={a.remove}
      onRetry={a.retry}
      onClose={() => {}}
    />
  );
}

describe("Pictures menu (useArtsets + SetPicker)", () => {
  let storage: MemoryStorage;
  let api: FakeApi;
  let download: FakeDownload;
  beforeEach(async () => {
    storage = new MemoryStorage();
    api = new FakeApi();
    download = new FakeDownload();
    await download.init();
    vi.stubGlobal("URL", {
      createObjectURL: vi.fn(() => "blob:x"),
      revokeObjectURL: vi.fn(),
    });
  });

  it("makes a set → generating → ready → auto-downloads → becomes active", async () => {
    render(<Harness api={api} download={download} storage={storage} />);
    await screen.findByText("Default");

    // ＋ New set → "Same style, fresh pictures" (a re-roll).
    await userEvent.click(screen.getByRole("button", { name: "＋ New set" }));
    await userEvent.click(screen.getByRole("button", { name: "Same style, fresh pictures" }));
    expect(api.createCalls).toEqual([{ kind: "reroll", style_id: undefined }]);

    // The new row shows it's being made; then the server finishes it.
    await screen.findByText("Making your pictures…");
    api.markReady(NEW_SET);

    // Poll picks up ready → auto-download → auto-switch. The new set ends up in use + resident.
    await waitFor(async () => expect(await readActiveSet(storage, USER, BOOK)).toBe(NEW_SET), {
      timeout: 2000,
    });
    expect(await storage.exists(`artsets/${USER}/${BOOK}/${NEW_SET}/manifest.local.json`)).toBe(true);
    await waitFor(() => {
      const newRow = screen
        .getAllByRole("listitem")
        .find((r) => r.getAttribute("data-set-id") === NEW_SET)!;
      expect(within(newRow).getByText("✓ In use")).toBeInTheDocument();
    });
  });

  it("makes a set in a chosen style (passes the style_id)", async () => {
    render(<Harness api={api} download={download} storage={storage} />);
    await screen.findByText("Default");
    await userEvent.click(screen.getByRole("button", { name: "＋ New set" }));
    await userEvent.click(screen.getByRole("button", { name: "Victorian Engraving" }));
    expect(api.createCalls).toEqual([{ kind: "style", style_id: "engraving" }]);
  });

  it("deletes a set and reverts to Default when it was active", async () => {
    // Seed a ready, resident, active personal set.
    api.sets.set(NEW_SET, { set_id: NEW_SET, kind: "style", label: "Engraving", status: "ready" });
    await storage.writeText(`artsets-active/${USER}/${BOOK}.json`, JSON.stringify({ set_id: NEW_SET }));
    await storage.writeText(`artsets/${USER}/${BOOK}/${NEW_SET}/manifest.local.json`, "{}");

    render(<Harness api={api} download={download} storage={storage} />);
    await screen.findByText("Engraving");

    await userEvent.click(screen.getByRole("button", { name: "Delete Engraving" }));

    await waitFor(() => expect(screen.queryByText("Engraving")).not.toBeInTheDocument());
    expect(api.deleteCalls).toEqual([NEW_SET]);
    expect(await readActiveSet(storage, USER, BOOK)).toBe("default");
    expect(await storage.exists(`artsets/${USER}/${BOOK}/${NEW_SET}/manifest.local.json`)).toBe(false);
  });

  it("offline: shows the note, keeps Default, and disables making a set", async () => {
    api.offline = true;
    render(<Harness api={api} download={download} storage={storage} />);
    await screen.findByText(/Connect to your home server/);
    expect(screen.getByText("Default")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "＋ New set" })).not.toBeInTheDocument();
  });
});
