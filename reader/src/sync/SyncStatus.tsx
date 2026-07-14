import type { SyncStatus } from "./useSync";

// The sync-status indicator (DESIGN §13). A small, unobtrusive badge: a cloud-off glyph when the
// server is unreachable, otherwise the last-synced time. Clicking it triggers a manual sync (forced,
// so a stale reachability cache can't stall it). Rendered in the app header and the reader bar.

function relativeTime(iso: string | null, nowMs: number): string {
  if (!iso) return "not yet";
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "just now";
  const secs = Math.max(0, Math.round((nowMs - then) / 1000));
  if (secs < 60) return "just now";
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs} h ago`;
  return `${Math.round(hrs / 24)} d ago`;
}

export function SyncStatusBadge({
  status,
  now = Date.now(),
}: {
  status: SyncStatus;
  now?: number;
}) {
  const offline = status.online === false;
  const label = offline ? "Offline" : `Synced ${relativeTime(status.lastSyncedAt, now)}`;
  return (
    <button
      type="button"
      className={`sync-badge${offline ? " sync-badge-off" : ""}`}
      title={offline ? "Server unreachable — changes are saved locally and will sync later" : "Tap to sync now"}
      aria-label={`Sync status: ${label}. Tap to sync now.`}
      onClick={() => void status.syncNow(true)}
    >
      <span aria-hidden="true">{offline ? "⛅✕" : "☁︎"}</span> {label}
    </button>
  );
}
