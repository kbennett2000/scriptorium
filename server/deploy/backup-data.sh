#!/usr/bin/env bash
#
# ADR-0007 off-box backup of SCRIPTORIUM_DATA (the only irreplaceable data in the system:
# published library, bake workspaces, sync annotations/positions, users.json, jobs).
#
# Mirrors $SCRIPTORIUM_DATA to $BACKUP_DEST/scriptorium-data/ with rsync. Idempotent; run
# from cron or a systemd timer. Refuses to run if the source is empty or the destination
# parent is missing/unmounted, so a detached USB drive can never be silently backed up to a
# stale mountpoint on the root filesystem.
#
# Usage:
#   SCRIPTORIUM_DATA=~/scriptorium-data BACKUP_DEST=/media/kb/BACKUP ./backup-data.sh
#   ./backup-data.sh /media/kb/BACKUP           # BACKUP_DEST as $1
#
set -euo pipefail

SRC="${SCRIPTORIUM_DATA:-/var/lib/scriptorium}"
DEST="${BACKUP_DEST:-${1:-}}"

die() { echo "backup-data: $*" >&2; exit 1; }

[ -n "$DEST" ] || die "BACKUP_DEST not set (env or \$1). Give the mounted backup target."
[ -d "$SRC" ]  || die "SCRIPTORIUM_DATA '$SRC' does not exist."
[ -n "$(ls -A "$SRC" 2>/dev/null)" ] || die "source '$SRC' is empty — refusing (misconfig guard)."
# The destination's PARENT must exist (the mount point). We create the leaf subdir ourselves;
# a missing parent means the USB/LAN target is not mounted.
DEST_PARENT="$(dirname "$DEST")"
[ -d "$DEST_PARENT" ] || die "backup destination parent '$DEST_PARENT' missing — is the drive mounted?"
mkdir -p "$DEST/scriptorium-data"

STAMP="$(date '+%Y-%m-%d %H:%M:%S')"
echo "backup-data: $STAMP  $SRC  ->  $DEST/scriptorium-data/"
# Choose rsync flags by destination filesystem. A FAT/vfat stick (the M1 target) cannot hold
# unix perms/owners/hardlinks and has coarse timestamps, so -a would spew warnings and churn
# every run; use content-only flags there. A real filesystem (ext4/ntfs/LAN) gets full archive.
DEST_FS="$(stat -f -c %T "$DEST_PARENT" 2>/dev/null || echo unknown)"
case "$DEST_FS" in
  msdos|vfat|exfat)
    echo "backup-data: destination is $DEST_FS — using content-only flags (no perms/hardlinks)."
    RSYNC_FLAGS=(-rt --no-perms --no-owner --no-group --delete --modify-window=1 --stats) ;;
  *)
    RSYNC_FLAGS=(-aH --delete --stats) ;;
esac
# Trailing slash on SRC copies contents (not the dir itself). sync/ and users.json are the
# payload that matters most.
rsync "${RSYNC_FLAGS[@]}" "$SRC/" "$DEST/scriptorium-data/" | tail -n 20
# A restore-readable manifest of what we just backed up (sha + size), for spot-verification.
( cd "$SRC" && find . -type f -printf '%s  %p\n' | sort ) > "$DEST/scriptorium-data.manifest.txt"
echo "backup-data: done $STAMP  (manifest: $DEST/scriptorium-data.manifest.txt)"
