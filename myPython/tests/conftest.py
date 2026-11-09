"""Make the project's modules importable from the tests (they live in the parent folder)."""

import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parent.parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


import pytest


@pytest.fixture(autouse=True)
def _clean_settings(monkeypatch):
    """Start every test from the DEFAULT settings.

    myconfig.py loads your real .env into os.environ when it is imported, so without this a test
    that expects a default (SEARX_QUERIES = 4) would fail on a machine whose .env says 6.
    Tests that want a value set it themselves (mock.patch.dict / monkeypatch.setenv).
    """
    import os

    for name in list(os.environ):
        if name.startswith(("SEARX_", "EXPAND_", "OPENROUTER_")):
            monkeypatch.delenv(name, raising=False)
