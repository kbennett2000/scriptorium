#!/usr/bin/env sh
# Apply DB migrations (idempotent) then serve. The `db` service is gated by a healthcheck in
# docker-compose.yml (depends_on: condition: service_healthy), so Postgres is already accepting
# connections by the time this runs.
set -e

echo "[entrypoint] applying migrations..."
python manage.py migrate --noinput

echo "[entrypoint] starting gunicorn on :8000"
exec gunicorn gutendex.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 3 \
    --timeout 120
