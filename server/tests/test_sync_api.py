"""Sync API tests (DESIGN §12) — the endpoints wrapping the pure merge.

Covers the users loader (committed-sample fallback + on-disk override), annotations/positions
round-trips and merge-on-PUT, the backup prune-to-20, schema validation both ways, the
``{user}``/``{book}`` traversal guard, and — the headline — that two interleaved async PUTs never
lose an update (the per-``(user, book)`` lock's proof).

Never asserts annotation/position *content* beyond ids/shape (CLAUDE.md).
"""

from __future__ import annotations

import asyncio
import json

import httpx
import jsonschema
import pytest
from fastapi.testclient import TestClient

from scriptorium.app import app


@pytest.fixture
def seeded(monkeypatch, tmp_path):
    monkeypatch.setenv("SCRIPTORIUM_DATA", str(tmp_path))
    return TestClient(app), tmp_path


def _ann(id_, modified, *, book="pg-35", user="kris"):
    return {
        "book_id": book,
        "user_id": user,
        "annotations": [
            {
                "id": id_,
                "type": "highlight",
                "page_id": "0007",
                "anchor": {"start": 10, "end": 20},
                "color": "yellow",
                "created": "2026-01-01T00:00:00Z",
                "modified": modified,
                "deleted": False,
            }
        ],
    }


def _pos(page_seq, modified, *, char=0):
    return {
        "furthest": {"page_seq": page_seq, "char": char, "modified": modified},
        "current": {"page_seq": page_seq, "char": char, "modified": modified},
    }


# ------------------------------------------------------------------------------------------- users


def test_users_sample_fallback(seeded):
    client, _ = seeded  # no users.json on disk → committed sample
    r = client.get("/api/users")
    assert r.status_code == 200
    ids = {u["id"] for u in r.json()}
    assert {"kris", "amy", "junior"} <= ids


def test_users_on_disk_override(seeded):
    client, tmp_path = seeded
    (tmp_path / "users.json").write_text(
        json.dumps([{"id": "solo", "name": "Solo", "color": "#123456"}])
    )
    assert [u["id"] for u in client.get("/api/users").json()] == ["solo"]


def test_users_malformed_is_surfaced_not_masked(seeded):
    client, tmp_path = seeded
    bad = [{"id": "NoCaps!", "name": "x", "color": "#fff"}]
    (tmp_path / "users.json").write_text(json.dumps(bad))
    # An invalid hand-edit must not be served as-is; it propagates rather than reaching the reader.
    with pytest.raises(jsonschema.ValidationError):
        client.get("/api/users")


# ------------------------------------------------------------------------------------- annotations


def test_annotations_get_empty_default(seeded):
    client, _ = seeded
    r = client.get("/api/sync/annotations/kris/pg-35")
    assert r.status_code == 200
    assert r.json() == {"book_id": "pg-35", "user_id": "kris", "annotations": []}


def test_annotations_put_merges_union(seeded):
    client, _ = seeded
    client.put("/api/sync/annotations/kris/pg-35", json=_ann("a", "2026-01-01T10:00:00Z"))
    r = client.put("/api/sync/annotations/kris/pg-35", json=_ann("b", "2026-01-01T11:00:00Z"))
    assert r.status_code == 200
    ids = {a["id"] for a in r.json()["annotations"]}
    assert ids == {"a", "b"}  # union across the two PUTs

    # A later edit to an existing id wins wholesale.
    later = _ann("a", "2026-01-01T20:00:00Z")
    later["annotations"][0]["color"] = "pink"
    r2 = client.put("/api/sync/annotations/kris/pg-35", json=later)
    a_entry = next(a for a in r2.json()["annotations"] if a["id"] == "a")
    assert a_entry["color"] == "pink"


def test_annotations_backup_prune_to_20(seeded):
    client, tmp_path = seeded
    for i in range(25):
        client.put("/api/sync/annotations/kris/pg-35", json=_ann(f"id-{i}", "2026-01-01T10:00:00Z"))
    backup_dir = tmp_path / "sync" / "annotations-backups" / "kris" / "pg-35"
    backups = sorted(backup_dir.glob("*.json"))
    assert len(backups) == 20  # newest 20 kept
    assert backups == sorted(backups)  # ns filenames → lexical order == chronological


def test_annotations_invalid_body_422_and_nothing_written(seeded):
    client, tmp_path = seeded
    bad = {"book_id": "pg-35", "user_id": "kris", "annotations": [{"id": "x"}]}  # missing required
    r = client.put("/api/sync/annotations/kris/pg-35", json=bad)
    assert r.status_code == 422
    assert not (tmp_path / "sync" / "annotations" / "kris" / "pg-35.json").exists()


def test_annotations_identity_mismatch_400(seeded):
    client, _ = seeded
    body = _ann("a", "2026-01-01T10:00:00Z", user="someone-else")
    r = client.put("/api/sync/annotations/kris/pg-35", json=body)
    assert r.status_code == 400


@pytest.mark.parametrize("user,book", [
    ("UPPER", "pg-35"),         # uppercase fails the user pattern
    ("kris", "not-a-book"),     # book id shape
])
def test_bad_ids_rejected_400(seeded, user, book):
    """A well-formed request with an out-of-pattern id is rejected by the guard with 400."""
    client, _ = seeded
    assert client.get(f"/api/sync/annotations/{user}/{book}").status_code == 400


@pytest.mark.parametrize("user,book", [
    ("%2e%2e", "pg-35"),        # encoded '..' as a path segment
    ("kris", "%2e%2e"),
])
def test_encoded_traversal_never_escapes(seeded, tmp_path, user, book):
    """Encoded ``..`` segments are rejected and never read outside ``sync_dir``.

    The exact code differs by server (TestClient → 400 via the pattern guard; a real ASGI server
    normalizes ``..`` and the two-segment route simply doesn't match → 404). Either way it is a
    rejection, and a secret planted a level up is never served.
    """
    client, _ = seeded
    (tmp_path / "secret.json").write_text('{"leak": true}')
    r = client.get(f"/api/sync/annotations/{user}/{book}")
    assert r.status_code in (400, 404)
    assert "leak" not in r.text


# --------------------------------------------------------------------------------------- positions


def test_positions_get_404_when_absent(seeded):
    client, _ = seeded
    assert client.get("/api/sync/positions/kris/pg-35").status_code == 404


def test_positions_put_furthest_wins(seeded):
    client, _ = seeded
    client.put("/api/sync/positions/kris/pg-35", json=_pos(50, "2026-01-01T10:00:00Z"))
    # A later write to an earlier page: current moves back, furthest stays at 50.
    r = client.put("/api/sync/positions/kris/pg-35", json=_pos(30, "2026-01-01T12:00:00Z"))
    assert r.status_code == 200
    assert r.json()["furthest"]["page_seq"] == 50
    assert r.json()["current"]["page_seq"] == 30


# ------------------------------------------------------------------------------------- concurrency


async def test_concurrent_puts_never_lose_an_update(monkeypatch, tmp_path):
    """Two interleaved async PUTs of distinct annotations → both survive (the lock's proof)."""
    monkeypatch.setenv("SCRIPTORIUM_DATA", str(tmp_path))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await asyncio.gather(
            client.put("/api/sync/annotations/kris/pg-35", json=_ann("a", "2026-01-01T10:00:00Z")),
            client.put("/api/sync/annotations/kris/pg-35", json=_ann("b", "2026-01-01T10:00:01Z")),
        )
        final = await client.get("/api/sync/annotations/kris/pg-35")
    ids = {a["id"] for a in final.json()["annotations"]}
    assert ids == {"a", "b"}  # neither PUT clobbered the other
