import type { Artset, ArtsetList } from "@scriptorium/shared";

import { ApiError } from "./client";

// The reader's picture-set control client (ADR-0014 Phase 4): list / create / delete a user's sets and
// list the art-style catalog. Lives in shelf/ because it touches the network, which the ESLint fence
// permits only here and in sync/. The file-bytes/manifest download client is HttpArtsetClient
// (artsetCheckout.ts); this one is the CRUD + catalog surface the "Pictures" menu drives.
//
// No auth (ADR-0005, LAN trust). Base URL is same-origin in prod (the i5 serves the reader at /); a dev
// override lets the reader run against a LAN server.

const BASE = import.meta.env.VITE_SERVER_URL ?? "";

/** One art style for the "New set" picker (a subset of the styles.json catalog entry). */
export interface StyleOption {
  id: string;
  name: string;
  consistency_friendly: boolean;
}

export interface CreateSetBody {
  kind: "style" | "reroll";
  style_id?: string;
  label?: string;
}

export interface ArtsetApi {
  fetchSetList(user: string, book: string): Promise<ArtsetList>;
  createSet(user: string, book: string, body: CreateSetBody): Promise<Artset>;
  deleteSet(user: string, book: string, setId: string): Promise<void>;
  fetchStyles(): Promise<StyleOption[]>;
}

function seg(s: string): string {
  return encodeURIComponent(s);
}

export class HttpArtsetApi implements ArtsetApi {
  async fetchSetList(user: string, book: string): Promise<ArtsetList> {
    return this.getJson<ArtsetList>(`/api/artsets/${seg(user)}/${seg(book)}`);
  }

  async createSet(user: string, book: string, body: CreateSetBody): Promise<Artset> {
    const resp = await fetch(`${BASE}/api/artsets/${seg(user)}/${seg(book)}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!resp.ok) throw new ApiError(resp.status, `POST create set → ${resp.status}`);
    return (await resp.json()) as Artset;
  }

  async deleteSet(user: string, book: string, setId: string): Promise<void> {
    const resp = await fetch(`${BASE}/api/artsets/${seg(user)}/${seg(book)}/${seg(setId)}`, {
      method: "DELETE",
    });
    if (!resp.ok) throw new ApiError(resp.status, `DELETE set → ${resp.status}`);
  }

  async fetchStyles(): Promise<StyleOption[]> {
    // The shipped style catalog (data/styles.json), served unauthenticated on the LAN.
    const doc = await this.getJson<{ styles: StyleOption[] }>("/api/admin/styles");
    return doc.styles ?? [];
  }

  private async getJson<T>(path: string): Promise<T> {
    const resp = await fetch(`${BASE}${path}`);
    if (!resp.ok) throw new ApiError(resp.status, `GET ${path} → ${resp.status}`);
    return (await resp.json()) as T;
  }
}
