"""
mykill.py - find the applications that are running right now (so that `kill <name>` can close them).

How do we know what is running? We ask the system for its process list:

    ps -axo pid=,command=
      812 /Applications/Obsidian.app/Contents/MacOS/Obsidian --some-flag
      977 /System/Applications/Notes.app/Contents/MacOS/Notes

The main program of every application lives in  <Name>.app/Contents/MacOS/. Helper processes (the
many "Google Chrome Helper" processes) live deeper, inside another .app, so we skip them: one
application = one line in our list, with all its process ids (pids) in case it has several.

We skip /System/Library/ (the Dock, Finder, loginwindow...: closing those is never what you want)
and the names in kill.protected (by default "python": that is this launcher itself).

Pure functions here: the `runner` that runs `ps` is given from outside, so tests can pretend.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# "  812 /Applications/Visual Studio Code.app/Contents/MacOS/Electron --flag"
#   pid  ^^^^^^^^^^ the bundle path (spaces allowed, ends in .app) ^^^^
PROCESS_LINE = re.compile(r"^\s*(\d+)\s+(.+?\.app)/Contents/MacOS/")


@dataclass(frozen=True)
class RunningApp:
    name: str  # "Obsidian"
    path: str  # "/Applications/Obsidian.app"
    pids: tuple  # (812,)


def running_apps(runner, protected=()) -> list:
    """The applications running now, sorted by name. `runner(command)` must return an object with .stdout."""
    try:
        output = runner(["ps", "-axo", "pid=,command="]).stdout or ""
    except (FileNotFoundError, OSError):
        return []
    found = {}
    for line in output.splitlines():
        match = PROCESS_LINE.match(line)
        if not match:
            continue
        pid, path = int(match.group(1)), match.group(2)
        if ".app/" in path or path.startswith("/System/Library/"):  # a helper inside another app, or system UI
            continue
        found.setdefault(path, []).append(pid)
    apps = []
    for path, pids in found.items():
        name = path.rsplit("/", 1)[-1].removesuffix(".app")
        if name.lower() not in protected:
            apps.append(RunningApp(name, path, tuple(sorted(pids))))
    return sorted(apps, key=lambda app: app.name.lower())


def alive(runner, pids) -> list:
    """Which of these pids still exist? (`ps -p 1,2,3` prints one line per process that exists.)"""
    if not pids:
        return []
    try:
        output = runner(["ps", "-p", ",".join(str(p) for p in pids), "-o", "pid="]).stdout or ""
    except (FileNotFoundError, OSError):
        return []
    present = {int(line) for line in output.split() if line.isdigit()}
    return [pid for pid in pids if pid in present]


def applescript_quote(text: str) -> str:
    """Make a path safe inside "..." of an AppleScript line."""
    return text.replace("\\", "\\\\").replace('"', '\\"')
