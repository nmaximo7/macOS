"""Shared helpers for the tests (no test cases in here)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "cli"
if str(CLI) not in sys.path:
    sys.path.insert(0, str(CLI))  # so that "import myconfig" works, exactly as when the scripts run

REAL_CONFIG = ROOT / "conf" / "myconfiguration.json"


def good_config(folders=(), **changes) -> dict:
    """A valid configuration as a dictionary; `changes` replaces top-level sections."""
    data = {
        "hotkey": {"modifiers": ["command", "shift"], "key": "d"},
        "apps": {"folders": [str(f) for f in folders], "exclude": []},
        "search": {"max_results": 8, "ignore_accents": True, "fuzzy": True},
        "commands": [
            {"id": "shutdown", "title": "Shutdown", "action": "shutdown", "keywords": ["power off"], "confirm": True}
        ],
    }
    data.update(changes)
    return data


class TempDirCase(unittest.TestCase):
    """A test case with a fresh temporary folder in self.tmp (deleted afterwards)."""

    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.tmp = Path(holder.name)

    def make_apps(self, folder: str, *names: str) -> Path:
        """Create fake applications (empty folders called X.app) and return their parent folder."""
        parent = self.tmp / folder
        parent.mkdir(parents=True, exist_ok=True)
        for name in names:
            (parent / f"{name}.app").mkdir()
        return parent

    def write_config(self, data: dict) -> Path:
        path = self.tmp / "config.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path


class FakeRunner:
    """Replaces "really run a command": it only remembers what it was asked to run."""

    def __init__(self, returncode: int = 0, stderr: str = "", error: Exception | None = None):
        self.calls = []
        self.returncode, self.stderr, self.error = returncode, stderr, error

    def __call__(self, command):
        self.calls.append(command)
        if self.error:
            raise self.error
        from types import SimpleNamespace

        return SimpleNamespace(returncode=self.returncode, stderr=self.stderr, stdout="")
