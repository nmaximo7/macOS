"""
myapps.py - find the applications installed on the Mac.

On macOS an application is just a FOLDER whose name ends in ".app", for example
/Applications/Obsidian.app. So "finding the apps" means: look inside a few folders and keep
every entry whose name ends in ".app". The folders to look in come from the configuration
("apps.folders"), so you can add your own without touching the code.

We do NOT look inside sub-folders: /Applications/Utilities is a folder, not an app, so if you want
its apps you list that folder too (the default configuration already does).
"""

from __future__ import annotations

from pathlib import Path


def find_apps(folders, exclude=()) -> list:
    """Return a list of (name, path) for every .app inside `folders`, sorted by name.

    folders: the folders to look in, in order of importance.
    exclude: app names (lower case) to hide.

    If the same app name appears in two folders (say /Applications and ~/Applications), the
    first folder wins; that is why the order of the folders matters.
    """
    found = {}  # name in lower case -> (name, path); a dictionary makes "already seen?" trivial
    for folder in folders:
        folder = Path(folder)
        if not folder.is_dir():
            continue  # a folder that does not exist (no ~/Applications yet) is not an error
        try:
            entries = sorted(folder.iterdir())  # sorted: the result is the same every time
        except OSError:
            continue  # no permission to read it: skip it
        for entry in entries:
            if entry.suffix.lower() != ".app" or not entry.is_dir():
                continue
            name = entry.stem  # "Obsidian.app" -> "Obsidian"
            key = name.lower()
            if key in exclude or key in found:
                continue
            found[key] = (name, entry)
    return sorted(found.values(), key=lambda pair: pair[0].lower())
