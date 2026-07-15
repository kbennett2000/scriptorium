"""App-level static-serving concerns: the ``/admin`` trailing-slash redirect and the startup
data-dir writability check.

The admin SPA is mounted at ``/admin`` and Starlette only serves it under ``/admin/``; a bare
``/admin`` (typed in the address bar, or an old link) must redirect rather than 404. Separately,
an unwritable data dir (``SCRIPTORIUM_DATA`` unset on a dev box, defaulting to the packaged path)
should be flagged loudly at startup, not surface later as scattered per-request 500s.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi.testclient import TestClient

from scriptorium.app import _check_data_dir, app
from scriptorium.config import Config


def _cfg(data_dir: Path) -> Config:
    return Config(
        data_dir=data_dir, port=8720, tts_url=None, imagegen_url=None, gpu_mac=None,
        gpu_wol_enabled=False, runner_tick_s=1, shared_dir=Path("shared"),
    )


def test_admin_without_slash_redirects_to_admin_slash() -> None:
    resp = TestClient(app).get("/admin", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/admin/"


def test_check_data_dir_creates_a_missing_dir(tmp_path) -> None:
    target = tmp_path / "fresh" / "data"
    _check_data_dir(_cfg(target))
    assert target.is_dir()


def test_check_data_dir_logs_when_unwritable(tmp_path, caplog) -> None:
    # A file where a directory should be → mkdir raises; the check must log, not raise.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a dir", encoding="utf-8")
    with caplog.at_level(logging.ERROR, logger="scriptorium"):
        _check_data_dir(_cfg(blocker / "data"))
    assert any("SCRIPTORIUM_DATA" in r.message for r in caplog.records)
