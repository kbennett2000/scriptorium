"""Review-gate endpoints (DESIGN §11.1, §4.3) — the S9 acceptance boxes.

Uses plain ``TestClient(app)`` (no lifespan → no runner) with ``SCRIPTORIUM_DATA=tmp_path`` like
``test_admin_books.py``. A book is created through the real P0 endpoint, then hand-seeded with the
``selection``/``cast``/``prompts`` artifacts P4/P5 would produce and moved to ``prompts_draft``, so
the review endpoints operate on schema-valid inputs. Assertions are schema/shape/cross-reference
only — never LLM/image content.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scriptorium.app import app
from scriptorium.bake import job as jobmod
from scriptorium.config import load_config

MD = (Path(__file__).parent / "fixtures" / "sources" / "frontmatter.md").read_text("utf-8")


@pytest.fixture
def client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setenv("SCRIPTORIUM_DATA", str(tmp_path))
    return TestClient(app)


def _prompt(page_id: str, prompt: str) -> dict:
    return {"page_id": page_id, "derived": {"prompt": prompt},
            "edited_prompt": None, "final_subject_prompt": prompt}


def _selection(plates) -> dict:
    return {
        "preset": "classic",
        "params": {"min_gap": 2, "max_gap": 6, "salience_floor": 0.55,
                   "chapter_open": True, "scene_boundary": True},
        "plates": plates,
    }


def _create(client: TestClient) -> str:
    resp = client.post("/api/admin/books", json={
        "source": {"kind": "markdown", "text": MD, "filename": "frontmatter.md"},
        "bake": {"style_id": "engraving", "density_preset": "classic", "portraits_enabled": True},
    })
    assert resp.status_code == 200, resp.text
    return resp.json()["book_id"]


def _seed_review(client: TestClient, tmp_path: Path, *, extra_plates=()) -> str:
    """Create a book and hand-seed P4/P5 artifacts, leaving it at ``prompts_draft``."""
    book_id = _create(client)
    work = tmp_path / "work" / book_id
    # frontmatter.md → 3 pages 0001..0003. Give 0001 a ledger so the review exposes a beat.
    page = json.loads((work / "pages" / "0001.json").read_text("utf-8"))
    page["ledger"] = {"location": "the workshop", "time_of_day": "night", "atmosphere": "lamplit",
                      "present": ["the Keeper"], "scene_changed": True, "visual_salience": 0.82,
                      "best_visual_beat": "the keeper trims the great lamp", "carry_notes": ""}
    (work / "pages" / "0001.json").write_text(json.dumps(page), encoding="utf-8")

    plates = [
        {"page_id": "0001", "reason": "chapter_open", "salience": 0.82,
         "status": "selected", "added_in_revision": 1},
        {"page_id": "0003", "reason": "fill", "salience": 0.6,
         "status": "selected", "added_in_revision": 1},
        *extra_plates,
    ]
    (work / "selection.json").write_text(json.dumps(_selection(plates)), encoding="utf-8")

    prompts = work / "prompts"
    prompts.mkdir(parents=True, exist_ok=True)
    for pid, text in [("0001", "a lamplit workshop"), ("0003", "a clock tower"),
                      ("cover", "frontispiece for the book"),
                      ("portrait-the-keeper", "a bust portrait of the keeper")]:
        (prompts / f"{pid}.json").write_text(json.dumps(_prompt(pid, text)), encoding="utf-8")

    (work / "cast.json").write_text(json.dumps({"characters": [
        {"slug": "the-keeper", "name": "the Keeper", "aliases": ["Keeper"],
         "mention_pages": ["0001", "0003"], "major": True,
         "visual_description": "a stooped lamplighter in a long coat",
         "one_line": "Tends the lamp.", "tags": ["lamplighter"],
         "portrait": None, "edited_by_human": False},
    ]}), encoding="utf-8")

    cfg = load_config()
    job = jobmod.load(cfg, book_id)
    job.state = "prompts_draft"
    job.prompt_warnings = {"0003": ["input truncated to fit the generation budget"]}
    job.save(cfg)
    return book_id


# --- review payload ---------------------------------------------------------


def test_review_payload_shape_and_warnings(client, tmp_path) -> None:
    book_id = _seed_review(client, tmp_path)
    r = client.get(f"/api/admin/books/{book_id}/review")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "prompts_draft"
    assert {p["page_id"] for p in body["prompts"]} == {
        "0001", "0003", "cover", "portrait-the-keeper"}
    assert [p["page_id"] for p in body["selection"]["plates"]] == ["0001", "0003"]
    assert body["cast"]["characters"][0]["slug"] == "the-keeper"
    assert body["beats"]["0001"] == "the keeper trims the great lamp"
    assert body["prompt_warnings"]["0003"]  # surfaced next to the plate (S8 → S9)


def test_review_409_before_p5(client) -> None:
    book_id = _create(client)  # freshly ingested: no selection/prompts yet
    assert client.get(f"/api/admin/books/{book_id}/review").status_code == 409


# --- prompt edit (acceptance box #3) ----------------------------------------


def test_prompt_edit_persists_and_recomputes(client, tmp_path) -> None:
    book_id = _seed_review(client, tmp_path)
    r = client.put(f"/api/admin/books/{book_id}/review/prompt/0001",
                   json={"edited_prompt": "a warmer, brighter workshop scene"})
    assert r.status_code == 200, r.text
    assert r.json()["final_subject_prompt"] == "a warmer, brighter workshop scene"

    on_disk = json.loads(
        (tmp_path / "work" / book_id / "prompts" / "0001.json").read_text("utf-8"))
    assert on_disk["edited_prompt"] == "a warmer, brighter workshop scene"
    assert on_disk["final_subject_prompt"] == "a warmer, brighter workshop scene"

    # Clearing the edit falls back to derived.prompt.
    r2 = client.put(f"/api/admin/books/{book_id}/review/prompt/0001", json={"edited_prompt": None})
    assert r2.json()["final_subject_prompt"] == "a lamplit workshop"


def test_prompt_edit_pseudo_plate(client, tmp_path) -> None:
    book_id = _seed_review(client, tmp_path)
    r = client.put(f"/api/admin/books/{book_id}/review/prompt/cover",
                   json={"edited_prompt": "an engraved frontispiece, dawn light"})
    assert r.status_code == 200
    assert r.json()["final_subject_prompt"] == "an engraved frontispiece, dawn light"


def test_prompt_edit_404_and_409(client, tmp_path) -> None:
    book_id = _seed_review(client, tmp_path)
    assert client.put(f"/api/admin/books/{book_id}/review/prompt/9999",
                      json={"edited_prompt": "x"}).status_code == 404
    # Move past the review window → edits are refused.
    cfg = load_config()
    job = jobmod.load(cfg, book_id)
    job.state = "approved"
    job.save(cfg)
    assert client.put(f"/api/admin/books/{book_id}/review/prompt/0001",
                      json={"edited_prompt": "x"}).status_code == 409


# --- manual selection add/remove (include toggle) ---------------------------


def test_selection_remove_keeps_prompt_then_readd(client, tmp_path) -> None:
    book_id = _seed_review(client, tmp_path)
    prompt_file = tmp_path / "work" / book_id / "prompts" / "0003.json"

    removed = client.put(f"/api/admin/books/{book_id}/review/selection", json={"remove": ["0003"]})
    assert removed.status_code == 200
    assert [p["page_id"] for p in removed.json()["plates"]] == ["0001"]
    assert prompt_file.is_file()  # prompt kept so the toggle round-trips

    readded = client.put(f"/api/admin/books/{book_id}/review/selection", json={"add": ["0003"]})
    plates = {p["page_id"]: p for p in readded.json()["plates"]}
    assert plates["0003"]["reason"] == "manual" and plates["0003"]["status"] == "selected"


def test_selection_add_rejects_non_page_id(client, tmp_path) -> None:
    book_id = _seed_review(client, tmp_path)
    assert client.put(f"/api/admin/books/{book_id}/review/selection",
                      json={"add": ["cover"]}).status_code == 400
    assert client.put(f"/api/admin/books/{book_id}/review/selection",
                      json={"add": ["0099"]}).status_code == 404  # no such page


# --- cast edit --------------------------------------------------------------


def test_cast_edit_sets_edited_by_human(client, tmp_path) -> None:
    book_id = _seed_review(client, tmp_path)
    r = client.put(f"/api/admin/books/{book_id}/review/cast/the-keeper",
                   json={"visual_description": "a tall lamplighter with a brass lantern"})
    assert r.status_code == 200
    assert r.json()["edited_by_human"] is True
    on_disk = json.loads((tmp_path / "work" / book_id / "cast.json").read_text("utf-8"))
    assert on_disk["characters"][0]["visual_description"] == \
        "a tall lamplighter with a brass lantern"
    assert client.put(f"/api/admin/books/{book_id}/review/cast/nobody",
                      json={"one_line": "x"}).status_code == 404


# --- approve (acceptance boxes #2 & #4) -------------------------------------


def test_approve_refuses_when_a_selected_plate_lacks_a_prompt(client, tmp_path) -> None:
    # Manually add page 0002, which has no prompts/0002.json → approve must refuse (box #2).
    book_id = _seed_review(client, tmp_path)
    client.put(f"/api/admin/books/{book_id}/review/selection", json={"add": ["0002"]})
    r = client.post(f"/api/admin/books/{book_id}/approve")
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["page_ids"] == ["0002"]
    # The job stayed in review (no partial transition).
    assert client.get(f"/api/admin/books/{book_id}").json()["state"] == "prompts_draft"


def test_approve_locks_shot_list(client, tmp_path) -> None:
    book_id = _seed_review(client, tmp_path)
    r = client.post(f"/api/admin/books/{book_id}/approve")
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "approved"
    selection = json.loads((tmp_path / "work" / book_id / "selection.json").read_text("utf-8"))
    assert {p["status"] for p in selection["plates"]} == {"approved"}


def test_approve_409_from_wrong_state(client, tmp_path) -> None:
    book_id = _seed_review(client, tmp_path)
    client.post(f"/api/admin/books/{book_id}/approve")
    # Already approved → cannot approve again.
    assert client.post(f"/api/admin/books/{book_id}/approve").status_code == 409
