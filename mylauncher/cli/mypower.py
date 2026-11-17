"""
mypower.py - restart or shut down the Mac even when something refuses to quit.

WHY `osascript ... restart` ALONE FAILS. macOS asks every application to quit and waits for all of them. One that
says "no" stops everything: Ghostty with a running btop / ssh ("close this terminal?"), a document asking to
save, or this very launcher (since step 9j it ignores quit requests: "Python failed to quit").

WHAT WE DO INSTEAD (a shell script started in the background, so it does not depend on the launcher):
  1. every other copy of the launcher (mylauncher_app.py) is stopped: two copies made the restart run twice;
  2. every application is asked to quit politely (like Cmd+Q);
  3. we wait `power.grace_seconds`; the ones still there are force quit (kill -KILL): their unsaved work is lost;
  4. only now the real restart / shutdown is requested, with nothing left to say "no".
The launcher itself is never killed by this script (it would take the script with it); it leaves by itself when
macOS announces the power-off (app/mylauncher_app.py).
With `power.force` = false only steps 1 and 4 happen (the polite way: macOS asks, and may wait for you).
"""

from __future__ import annotations

import os
import shlex
import time
from pathlib import Path

from mykill import applescript_quote, running_apps

LOCK_SECONDS = 120  # a second request within this time is ignored: "reboot two times" is a bug, not a wish


def other_instances(runner, own_pids) -> list:
    """Process ids of every `mylauncher_app.py` except the ones in `own_pids` (the program that is running us)."""
    try:
        output = runner(["pgrep", "-f", "mylauncher_app.py"]).stdout or ""
    except (FileNotFoundError, OSError):
        return []
    return [int(p) for p in output.split() if p.isdigit() and int(p) not in own_pids]


def already_asked(lock_path, now=time.time) -> bool:
    """True when a restart/shutdown was requested less than LOCK_SECONDS ago (the marker file is newer than that)."""
    if not lock_path:
        return False
    try:
        return now() - Path(lock_path).stat().st_mtime < LOCK_SECONDS
    except OSError:
        return False


def mark_asked(lock_path) -> None:
    """Write the marker: also read by the launcher, which then accepts the "quit" request of macOS."""
    if not lock_path:
        return
    try:
        path = Path(lock_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(int(time.time())), encoding="utf-8")
    except OSError:
        pass  # the marker only prevents doubles: never stop a restart because of it


def power_script(apps, force: bool, grace: int, final_command: list) -> str:
    """The shell script of steps 2 to 4 (see the top of this file)."""
    lines = ["# mylauncher: close everything, then ask macOS"]
    if force:
        for app in apps:
            lines.append(f"osascript -e {shlex.quote(f'tell application {chr(34)}{applescript_quote(app.path)}{chr(34)} to quit')} >/dev/null 2>&1 &")
        pids = sorted({pid for app in apps for pid in app.pids})
        lines.append(f"sleep {int(grace)}")
        for pid in pids:
            lines.append(f"kill -0 {pid} 2>/dev/null && kill -KILL {pid} 2>/dev/null")
        lines.append("sleep 1")
    lines.append(shlex.join(final_command))
    return "\n".join(lines)


def plan(runner, protected, own_pids) -> tuple:
    """(applications to close, other launcher copies)."""
    return running_apps(runner, tuple(protected)), other_instances(runner, set(own_pids))


def own_pids() -> set:
    """This process and its parent (the launcher window that started us): never touched."""
    return {os.getpid(), os.getppid()}
