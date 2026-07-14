import type { Annotations, Positions, Users } from "@scriptorium/shared";

// The reader's sync client — with shelf/, the ONLY place allowed to touch the network (DESIGN §13,
// ESLint-enforced). Talks to the S12 sync group: GET /api/users, and GET/PUT
// /api/sync/{annotations,positions}/{user}/{book}. Base URL and reachability mirror shelf/client.ts
// exactly (same-origin in prod; a dev override for a LAN server): a 2 s /health ping cached 60 s, and
// every failure is silent — the engine turns it into a cloud-off indicator, never an exception the
// reading path can see.

const BASE = import.meta.env.VITE_SERVER_URL ?? "";

const HEALTH_TIMEOUT_MS = 2000;
const REACH_CACHE_MS = 60_000;

/** Same shape as shelf's ApiError; kept local so sync/ has no cross-boundary import into shelf/. */
export class SyncApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "SyncApiError";
    this.status = status;
  }
}

export interface SyncClient {
  /** 2 s /health ping cached 60 s; `force` busts the cache (for user-initiated / reconnect syncs). */
  reachable(force?: boolean): Promise<boolean>;
  fetchUsers(): Promise<Users>;
  getAnnotations(user: string, book: string): Promise<Annotations>;
  putAnnotations(user: string, book: string, doc: Annotations): Promise<Annotations>;
  /** GET positions; resolves to `null` when the server has none yet (404 — DESIGN §12). */
  getPositions(user: string, book: string): Promise<Positions | null>;
  putPositions(user: string, book: string, doc: Positions): Promise<Positions>;
}

export class HttpSyncClient implements SyncClient {
  private reachCache: { value: boolean; at: number } | null = null;

  constructor(private now: () => number = () => Date.now()) {}

  async reachable(force = false): Promise<boolean> {
    const t = this.now();
    if (!force && this.reachCache && t - this.reachCache.at < REACH_CACHE_MS) {
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

  async fetchUsers(): Promise<Users> {
    return this.getJson<Users>("/api/users");
  }

  async getAnnotations(user: string, book: string): Promise<Annotations> {
    return this.getJson<Annotations>(`/api/sync/annotations/${enc(user)}/${enc(book)}`);
  }

  async putAnnotations(user: string, book: string, doc: Annotations): Promise<Annotations> {
    return this.putJson<Annotations>(`/api/sync/annotations/${enc(user)}/${enc(book)}`, doc);
  }

  async getPositions(user: string, book: string): Promise<Positions | null> {
    const resp = await fetch(`${BASE}/api/sync/positions/${enc(user)}/${enc(book)}`);
    if (resp.status === 404) return null;
    if (!resp.ok) throw new SyncApiError(resp.status, `GET positions → ${resp.status}`);
    return (await resp.json()) as Positions;
  }

  async putPositions(user: string, book: string, doc: Positions): Promise<Positions> {
    return this.putJson<Positions>(`/api/sync/positions/${enc(user)}/${enc(book)}`, doc);
  }

  private async getJson<T>(path: string): Promise<T> {
    const resp = await fetch(`${BASE}${path}`);
    if (!resp.ok) throw new SyncApiError(resp.status, `GET ${path} → ${resp.status}`);
    return (await resp.json()) as T;
  }

  private async putJson<T>(path: string, body: unknown): Promise<T> {
    const resp = await fetch(`${BASE}${path}`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!resp.ok) throw new SyncApiError(resp.status, `PUT ${path} → ${resp.status}`);
    return (await resp.json()) as T;
  }
}

function enc(segment: string): string {
  return encodeURIComponent(segment);
}
