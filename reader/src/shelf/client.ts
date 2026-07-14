import type { Manifest } from "@scriptorium/shared";

// The reader's library client — the ONLY place (besides sync/, R3) allowed to touch the network
// (DESIGN §13, ESLint-enforced). Talks to the S11 library group: GET /api/library,
// /api/library/{id}/manifest, /api/library/{id}/files/{path}. Base URL is same-origin in prod (the
// i5 serves the reader at /); a dev override lets the reader run against a LAN server.
//
// Reachability is a 2 s /health ping cached for 60 s: the shelf calls it to decide online/offline,
// and failure is silent (a cloud-off indicator), never an exception the reading path could see.

const BASE = import.meta.env.VITE_SERVER_URL ?? "";

const HEALTH_TIMEOUT_MS = 2000;
const REACH_CACHE_MS = 60_000;

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** One shelf listing row (the server's GET /api/library shape; not a bundle schema). */
export interface LibraryEntry {
  id: string;
  title: string;
  author: string;
  cover_thumb_url: string;
  revision: number;
  total_bytes_reader: number;
}

export interface LibraryClient {
  reachable(): Promise<boolean>;
  fetchLibrary(): Promise<LibraryEntry[]>;
  fetchManifest(bookId: string): Promise<Manifest>;
  fetchFileBytes(bookId: string, filePath: string): Promise<Uint8Array>;
}

export class HttpLibraryClient implements LibraryClient {
  private reachCache: { value: boolean; at: number } | null = null;

  constructor(private now: () => number = () => Date.now()) {}

  async reachable(): Promise<boolean> {
    const t = this.now();
    if (this.reachCache && t - this.reachCache.at < REACH_CACHE_MS) {
      return this.reachCache.value;
    }
    let value = false;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), HEALTH_TIMEOUT_MS);
    try {
      const resp = await fetch(`${BASE}/health`, { signal: controller.signal });
      value = resp.ok;
    } catch {
      value = false;
    } finally {
      clearTimeout(timer);
    }
    this.reachCache = { value, at: t };
    return value;
  }

  async fetchLibrary(): Promise<LibraryEntry[]> {
    return this.getJson<LibraryEntry[]>("/api/library");
  }

  async fetchManifest(bookId: string): Promise<Manifest> {
    return this.getJson<Manifest>(`/api/library/${encodeURIComponent(bookId)}/manifest`);
  }

  async fetchFileBytes(bookId: string, filePath: string): Promise<Uint8Array> {
    const url = `${BASE}/api/library/${encodeURIComponent(bookId)}/files/${filePath}`;
    const resp = await fetch(url);
    if (!resp.ok) throw new ApiError(resp.status, `GET ${filePath} → ${resp.status}`);
    return new Uint8Array(await resp.arrayBuffer());
  }

  private async getJson<T>(path: string): Promise<T> {
    const resp = await fetch(`${BASE}${path}`);
    if (!resp.ok) throw new ApiError(resp.status, `GET ${path} → ${resp.status}`);
    return (await resp.json()) as T;
  }
}
