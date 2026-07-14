// Small shared UI primitives + a data-loading hook. Kept minimal — the workbench needs legible
// loading/error states, not a data-fetching library.

import { useCallback, useEffect, useState } from "react";

import { ApiError } from "../api/client";

export function errorText(err: unknown): string {
  if (err instanceof ApiError) {
    if (typeof err.detail === "string") return err.detail;
    return `HTTP ${err.status}`;
  }
  if (err instanceof Error) return err.message;
  return String(err);
}

export interface Async<T> {
  data: T | null;
  error: unknown;
  loading: boolean;
  reload: () => void;
}

// Run `fn` on mount and whenever a dep changes; expose {data,error,loading,reload}. `fn` must be
// stable (wrap in useCallback at the call site or pass a primitive dep list).
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]): Async<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);
  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    let live = true;
    setLoading(true);
    setError(null);
    fn().then(
      (d) => {
        if (live) {
          setData(d);
          setLoading(false);
        }
      },
      (e) => {
        if (live) {
          setError(e);
          setLoading(false);
        }
      },
    );
    return () => {
      live = false;
    };
  }, [...deps, nonce]);

  return { data, error, loading, reload };
}

export function Notice({
  kind,
  children,
}: {
  kind: "warn" | "error" | "ok";
  children: React.ReactNode;
}) {
  return <div className={`notice ${kind}`}>{children}</div>;
}

// Render an error notice iff `error` is set. Takes `unknown` (the useAsync/catch error type) so
// call sites don't have to coerce — `{error && <Notice/>}` would otherwise type as `unknown`.
export function ErrorNotice({ error, prefix }: { error: unknown; prefix?: string }) {
  if (error == null) return null;
  return (
    <Notice kind="error">
      {prefix ? `${prefix}: ` : ""}
      {errorText(error)}
    </Notice>
  );
}

export function Loading({ what }: { what?: string }) {
  return <p className="muted">Loading{what ? ` ${what}` : ""}…</p>;
}

export function Crumbs({ children }: { children: React.ReactNode }) {
  return <div className="crumbs muted">{children}</div>;
}
