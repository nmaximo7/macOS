"""Make the project's modules importable from the tests (they live in the parent folder)."""
import os
import sys
from pathlib import Path

import pytest

ROOT = str(Path(__file__).resolve().parent.parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture(autouse=True)
def _clean_settings(monkeypatch):
    """Start every test from the DEFAULT settings (your real .env is loaded into os.environ)."""
    for name in list(os.environ):
        if name.startswith(("SEARX_", "EXPAND_", "OPENROUTER_")):
            monkeypatch.delenv(name, raising=False)
