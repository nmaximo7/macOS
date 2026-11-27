"""
myinstance.py - only ONE copy of the launcher at a time.

Two copies (one from the login item, one started by hand with `mlapp`) both catch Command+D and both react: windows
twice, a restart requested twice. A lock on a small file prevents it: the second copy finds the file locked, says
who has it and ends. The lock belongs to the process: when the first copy ends (even by a crash) the lock is free.

GUIDED TOUR: two layers, the second added later after a real problem.
  LAYER 1  acquire        "is somebody else running?" answered by a FILE LOCK.
  LAYER 2  stray_pids, list_processes, terminate, stop_old_instances      "make the NEWEST copy win": find the other copies by their COMMAND LINE, ask them to
                           stop, wait, and kill the stubborn ones.
FILE LOCK IN WORDS. fcntl.flock asks the operating system for an exclusive lock on an open file. LOCK_EX = exclusive; LOCK_NB = do not wait, fail at once if it is taken
(that failure is the OSError we catch). The lock belongs to the OPEN FILE of the PROCESS: when the program ends, even by a crash or kill -9, the system releases it. That
is why a lock file is better than "write my pid in a file and check it": a pid file can lie after a crash, a lock cannot. We still write our pid inside, only so a
second copy can SAY who holds it. The handle must be kept open for the life of the program (closing it releases the lock): "Keep `handle` until the end".
WHY LAYER 2? Layer 1 made the SECOND copy leave, so an old, stuck copy stayed for ever (you saw several "Python" entries in Force Quit, and a shutdown that waited
for them). Now the new copy stops the old ones. Safety rules in the code: only processes whose COMMAND LINE runs mylauncher_app.py are touched (never a pid read
from a file: pids get reused by other programs), and quick test modes (--keys...) do not count as "a copy".
terminate: signal 15 (SIGTERM, "please end") -> wait up to `patience` seconds, polling every 0.25 s -> signal 9 (SIGKILL, cannot be ignored) for what is left.
`kill(pid, 0)` sends NO signal: it only asks "does this process exist?" (ProcessLookupError = no; PermissionError = yes, but it is not ours). Same trick as chapter 11.
Everything that touches the system (kill, alive, sleep, ps) is a parameter: the tests use fakes, so no real process is ever killed.
Try it:   python3 -c "import sys; sys.path.insert(0,'app'); import myinstance as m; print(m.stray_pids('11 python /x/mylauncher_app.py\\n12 vim mylauncher_app.py\\n13 python /x/mylauncher_app.py --keys', 99))"
          (prints [11]: the editor is not an interpreter, and --keys is a test run)
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
    # Mode "a+" = read and append, creating the file if missing and WITHOUT erasing it (mode "w" would truncate the pid of the current owner before we know
    # whether we may take the lock). Only after the lock is ours do we truncate and write our own pid.
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


# ---- the NEWEST copy wins ------------------------------------------------------------------------------------------
# Before: a second copy found the lock taken and ended itself, so an old, stuck or half-dead copy stayed forever (you saw
# several "Python" entries in Force Quit, and a shutdown that waits for them). Now a starting copy first STOPS every other
# copy (asks nicely with SIGTERM, waits, then SIGKILL) and takes over. Only processes that really run mylauncher_app.py
# are touched: we look at the command line of every process (`ps`), never at a pid written in a file (pids get reused).

MARKER = "mylauncher_app.py"


def stray_pids(ps_text: str, me: int, marker: str = MARKER) -> list:
    """The pids (other than `me`) of programs that run mylauncher_app.py, from the text of `ps -axo pid=,command=`."""
    found = []
    for line in ps_text.splitlines():
        # `split(None, 1)` cuts at the FIRST run of whitespace only: ["12345", "/usr/bin/python3 /x/mylauncher_app.py --show"] = pid and the whole command.
        # `parts[0].isdigit()` guards against header or garbage lines; `words[1:3]` looks only at the first two words after the interpreter, so
        # "vim mylauncher_app.py" (an editor with the file as argument) or "tail -f mylauncher.log" is not mistaken for the app.
        parts = line.strip().split(None, 1)
        if len(parts) != 2 or not parts[0].isdigit() or int(parts[0]) == me:
            continue
        words = parts[1].split()
        # `python .../mylauncher_app.py [options]`: an interpreter, then the script (an editor, grep or tail of the log is not it)
        if "python" in words[0].lower() and any(w.endswith("/" + marker) or w == marker for w in words[1:3]) \
                and not {"--toast-test", "--timer-test", "--hotkey-test", "--keys"} & set(words):  # a quick test run is not "a copy"
            found.append(int(parts[0]))
    return found


def list_processes() -> str:
    import subprocess
    try:
        return subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def terminate(pids, kill=os.kill, alive=None, sleep=None, patience: float = 4.0) -> list:
    """SIGTERM, wait up to `patience` seconds, then SIGKILL what is still there. Returns the pids that needed SIGKILL."""
    import signal
    import time
    sleep = sleep or time.sleep

    def is_alive(pid):
        try:
            kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    alive = alive or is_alive
    for pid in pids:
        try:
            kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    # Count the waiting ourselves (0.25 s per lap) instead of reading the clock: with the fake `sleep` of a test this loop finishes instantly, yet follows the same logic.
    waited = 0.0
    while waited < patience and any(alive(p) for p in pids):
        sleep(0.25)
        waited += 0.25
    forced = [p for p in pids if alive(p)]
    for pid in forced:
        try:
            kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    return forced


def stop_old_instances(me=None, ps=list_processes, kill=os.kill, alive=None, sleep=None, patience: float = 4.0) -> tuple:
    """Stop every other copy of the launcher. Returns (pids stopped, pids that had to be killed)."""
    pids = stray_pids(ps(), os.getpid() if me is None else me)
    if not pids:
        return [], []
    return pids, terminate(pids, kill, alive, sleep, patience)
