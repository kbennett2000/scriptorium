# Self-hosted Gutendex

A local [Gutendex](https://github.com/garethbjohnson/gutendex) instance for scriptorium's
"Search free classic books" path. The public `gutendex.com` has been flaky (its search endpoint
hangs), so the bakery prefers this LAN instance and falls back to public only on error/no-match.

- **Stack:** Django + PostgreSQL, via Docker Compose (`db` + `gutendex`).
- **Host port:** `8721` → app `8000` (8712 TTS / 8189 imagegen / 8720 bakery are taken).
- **Data:** the Project Gutenberg catalog (~75k books) lives in the `gutendex-pgdata` volume,
  populated by the `updatecatalog` management command. The one external dependency that remains is
  `gutenberg.org` (catalog refresh + the actual book-text download).

## First-time bring-up

```sh
cd server/deploy/gutendex
cp .env.example .env            # then set SECRET_KEY and DATABASE_PASSWORD
docker compose up -d --build    # builds the image, starts Postgres + gunicorn
```

Health check (should be fast, unlike public):

```sh
curl -s "http://localhost:8721/books/?search=call%20of%20the%20wild" | head -c 300
```

## Import the catalog (required, and slow)

The DB is empty until you import. This downloads Project Gutenberg's nightly RDF archive
(`https://gutenberg.org/cache/epub/feeds/rdf-files.tar.bz2`, ~90 MB) and loads ~75k books — it
takes tens of minutes. The API answers for rows as they land.

```sh
docker compose exec gutendex python manage.py updatecatalog
```

Run it in the background and watch progress:

```sh
docker compose exec -d gutendex python manage.py updatecatalog
docker compose logs -f gutendex
```

## Refresh the catalog

Re-run the same command any time to pull the latest catalog:

```sh
docker compose exec gutendex python manage.py updatecatalog
```

(Optionally wire this to a weekly `cron` or systemd timer — not set up here.)

## Point the bakery at it

`server/deploy/scriptorium-bakery.env` sets `GUTENDEX_URL=http://localhost:8721`. Because
`uv run uvicorn` reads env once at startup, restart the bakery after changing it:

```sh
systemctl --user restart scriptorium-bakery.service
```

## Operations

```sh
docker compose ps                 # status
docker compose logs -f gutendex   # logs
docker compose down               # stop (keeps the pgdata volume)
docker compose down -v            # stop AND delete the catalog volume (full re-import needed)
```

Both services use `restart: unless-stopped`, so they come back after a reboot once the Docker
daemon is up.
