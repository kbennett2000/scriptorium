# scriptorium server — deploy

## ADR-0007 off-box backup of `SCRIPTORIUM_DATA`

`SCRIPTORIUM_DATA` (default `/var/lib/scriptorium`; on G434 for M1: `~/scriptorium-data`) is the
**only irreplaceable data in the system** — the published library, bake workspaces, sync
annotations/positions, `users.json`, and jobs. In-bundle content is reproducible from
`work/{id}/source/` + the pipeline; **annotations and positions are not**, so `sync/` +
`users.json` are the real payload. ADR-0007 requires a verified off-box backup before M1 closes.

### `backup-data.sh`

`rsync` mirror of `$SCRIPTORIUM_DATA` → `$BACKUP_DEST/scriptorium-data/`. Idempotent; refuses to
run if the source is empty or the destination's mount point is missing (so a detached drive can't
be backed up to a stale path on `/`). Writes a `scriptorium-data.manifest.txt` (size + path per
file) alongside for spot-verification.

```bash
SCRIPTORIUM_DATA=~/scriptorium-data BACKUP_DEST=/run/media/kb/<DRIVE> \
  server/deploy/backup-data.sh
```

The M1 target is the Phison `USB DISK 3.2` (28.9 GB, serial 587651035208) at
`/run/media/kb/TV`. It is **vfat**, so the script switches to content-only flags there (no unix
perms/owners/hardlinks — restored files come back owned by whoever runs the restore, which is
fine: the service re-owns its data dir). A future ext4/NTFS/LAN target gets full `-aH` archive
automatically.

### Restore (single file or whole tree)

The backup is a plain mirror — restore is a copy back:

```bash
# one file (e.g. a user's annotations):
rsync -a /media/kb/<DRIVE>/scriptorium-data/sync/annotations/<user>.json \
        ~/scriptorium-data/sync/annotations/<user>.json
# whole tree to a fresh box:
rsync -aH /media/kb/<DRIVE>/scriptorium-data/  ~/scriptorium-data/
```

### Scheduling

Run from cron (operator's crontab), e.g. hourly:

```
0 * * * * SCRIPTORIUM_DATA=/home/kb/scriptorium-data BACKUP_DEST=/media/kb/<DRIVE> /home/kb/Desktop/projects/scriptorium/server/deploy/backup-data.sh >> /home/kb/scriptorium-backup.log 2>&1
```

or a systemd `.timer` (install requires sudo — not committed here).

### Caveat (M1)

For M1 the target is an **external/USB drive mounted on G434**. That is removable media, physically
separable from the box, but it is *not* a networked off-site target — a fire/theft that takes the
box can take the drive. Sufficient to satisfy ADR-0007's "off-box" for the milestone; a LAN/off-site
restic target is the follow-up (filed in NOTES).

---

## Bakery service — `scriptorium-bakery.service`

The bakery (FastAPI, port 8720) runs as a **systemd user unit** so it survives logout and
restarts on failure. Two files here:

- `scriptorium-bakery.env` — `SCRIPTORIUM_DATA` + the GPU service URLs (`TTS_URL`,
  `IMAGEGEN_URL`). **These are why the service works:** without `SCRIPTORIUM_DATA` the app
  falls back to `/var/lib/scriptorium` and the library appears empty (writes 500); without the
  GPU URLs `/health` reports `degraded` and any bake parks in `waiting_gpu`.
- `scriptorium-bakery.service` — the unit; reads the env file, `WorkingDirectory` = this
  `server/` dir, `ExecStart` = `uv run uvicorn …`.

Install (user unit, no sudo — relies on `loginctl enable-linger kb`, already set):

```bash
ln -sf "$PWD/deploy/scriptorium-bakery.service" ~/.config/systemd/user/scriptorium-bakery.service
systemctl --user daemon-reload
systemctl --user enable --now scriptorium-bakery.service
systemctl --user status scriptorium-bakery.service
journalctl --user -u scriptorium-bakery.service -f      # logs
```

The unit is a symlink to this repo file, so editing `deploy/scriptorium-bakery.service` +
`systemctl --user daemon-reload` picks up changes. A bake survives a restart: job state is
persisted under `SCRIPTORIUM_DATA` and resumes from its last checkpoint (the in-flight
prompt/render step retries), so `systemctl --user restart` is safe.

> Ports: `TTS_URL` → text-transform-service :8712, `IMAGEGEN_URL` → imagegen-service :8189
> (which fronts ComfyUI :8188). imagegen-service serves whatever git branch is checked out in
> its repo — verify the branch after restarting it, not just that the PID is alive.

### Still deferred

- **No backup `.timer`** — `backup-data.sh` still runs from cron (above); a `.timer` install
  needs sudo and isn't committed here.
