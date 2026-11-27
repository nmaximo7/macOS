"""
myversion.py - which mylauncher is this? (the `about` command, `ml about`, `ml --version`).

VERSION and STEP are changed by hand at every delivery. FINGERPRINT is computed from the files that are really
on disk: if you copied only part of a zip (it happened: `cli/` was old and `app/` new), the fingerprint
differs from the one in the delivery notes and `about` shows how many files there are.

GUIDED READING: three constants and three functions.
  VERSION / STEP / BUILT   plain text you edit at each delivery (0.19.10, "Step 20.7", a date).
  ROOT                     the project folder: this file is cli/myversion.py, so `.parent` = cli/, `.parent.parent` = project.
  python_files()           every .py of cli/ and app/, sorted (sorted = the SAME order on every Mac, essential for a hash).
  fingerprint()            a "hash": a SHA-256 digest is a long number computed from bytes; change ONE byte of ANY file
                           and it changes completely. We feed it each file's name and content and keep the first 8 hex
                           characters. Two Macs with the same fingerprint have the same code, which is how you spot a
                           half-copied zip (old cli/ + new app/).
  one_line()               the sentence shown by `ml --version` and `ml about`.
Try it:  ml --version      ->  mylauncher 0.19.10 (Step 20.7, 2026-11-26) files 41, fingerprint 1a2b3c4d
"""

from __future__ import annotations

import hashlib
from pathlib import Path

VERSION = "0.19.19"
STEP = "Step 20.16"
BUILT = "2026-11-26"

ROOT = Path(__file__).resolve().parent.parent


def python_files(root: Path = ROOT) -> list:
    """The Python files that make up the program. `[*a, *b]` joins two lists; `glob("*.py")` finds files by pattern."""
    return sorted([*(root / "cli").glob("*.py"), *(root / "app").glob("*.py")])


def fingerprint(root: Path = ROOT) -> tuple:
    """(number of Python files, 8 hex characters that change when any of them changes)."""
    digest = hashlib.sha256()  # an empty "hasher"; .update(bytes) feeds it, .hexdigest() reads the result as text
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
