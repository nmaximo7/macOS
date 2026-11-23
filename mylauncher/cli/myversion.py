"""
myversion.py - which mylauncher is this? (the `about` command, `ml about`, `ml --version`).

VERSION and STEP are changed by hand at every delivery. FINGERPRINT is computed from the files that are really
on disk: if you copied only part of a zip (it happened: `cli/` was old and `app/` new), the fingerprint
differs from the one in the delivery notes and `about` shows how many files there are.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

VERSION = "0.16.0"
STEP = "Step 16"
BUILT = "2026-11-23"

ROOT = Path(__file__).resolve().parent.parent


def python_files(root: Path = ROOT) -> list:
    return sorted([*(root / "cli").glob("*.py"), *(root / "app").glob("*.py")])


def fingerprint(root: Path = ROOT) -> tuple:
    """(number of Python files, 8 hex characters that change when any of them changes)."""
    digest = hashlib.sha256()
    files = python_files(root)
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode())
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"?")
    return len(files), digest.hexdigest()[:8]


def one_line(root: Path = ROOT) -> str:
    count, fp = fingerprint(root)
    return f"{VERSION} ({STEP}, {BUILT}) files {count}, fingerprint {fp}"
