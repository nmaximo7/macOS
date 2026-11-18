"""
myinstance.py - only ONE copy of the launcher at a time.

Two copies (one from the login item, one started by hand with `mlapp`) both catch Command+D and both react: windows
twice, a restart requested twice. A lock on a small file prevents it: the second copy finds the file locked, says
who has it and ends. The lock belongs to the process: when the first copy ends (even by a crash) the lock is free.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    import fcntl
except ImportError:  # not on Unix: no lock, the launcher still works
    fcntl = None


def acquire(path):
    """(handle, "") if we are the only copy; (None, "pid of the other copy") otherwise. Keep `handle` until the end."""
    if fcntl is None:
        return object(), ""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+")  # noqa: SIM115 - it must stay open as long as the program runs
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.seek(0)
        other = handle.read().strip()
        handle.close()
        return None, other or "unknown"
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    return handle, ""
