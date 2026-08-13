# Self-hosted Gutendex (garethbjohnson/gutendex) for the scriptorium book-search path.
# The upstream repo ships no Dockerfile, so we build one: clone a pinned commit, install its
# requirements plus gunicorn, and serve the Django WSGI app. Catalog data lives in Postgres
# (the `db` compose service), not in the image — see README for the one-time import step.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# git: to fetch the pinned source. ca-certificates: HTTPS to github + gutenberg.org.
# tar/bzip2/rsync: the `updatecatalog` command shells out to them to extract and stage the
# nightly RDF archive (`tar fjvx ...` then `rsync`); the slim base ships none of them.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git ca-certificates tar bzip2 rsync \
    && rm -rf /var/lib/apt/lists/*

# Pin the exact commit so rebuilds are reproducible (override with --build-arg GUTENDEX_REF=...).
ARG GUTENDEX_REF=c3f75a8bd783ca91d9cd37d133028ff994e7ba4b
RUN git clone https://github.com/garethbjohnson/gutendex.git /app \
    && cd /app \
    && git checkout "${GUTENDEX_REF}"

WORKDIR /app

# psycopg2-binary ships its own libpq, so no build toolchain is needed. gunicorn is not in the
# upstream requirements — add it for a production-grade WSGI server (vs. manage.py runserver).
RUN pip install -r requirements.txt gunicorn

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
