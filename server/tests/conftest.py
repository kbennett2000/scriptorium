"""Pytest path setup: make repo-level ``tools/`` importable so tests can exercise the standalone
tooling (``verify_bundle``, the shared ``_pipeline_build`` harness) directly."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for extra in (_REPO_ROOT / "tools", Path(__file__).parent):
    p = str(extra)
    if p not in sys.path:
        sys.path.insert(0, p)
