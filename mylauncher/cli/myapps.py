"""
myapps.py - find the applications installed on the Mac.

On macOS an application is just a FOLDER whose name ends in ".app", for example
/Applications/Obsidian.app. So "finding the apps" means: look inside a few folders and keep
every entry whose name ends in ".app". The folders to look in come from the configuration
("apps.folders"), so you can add your own without touching the code.

We do NOT look inside sub-folders: /Applications/Utilities is a folder, not an app, so if you want
its apps you list that folder too (the default configuration already does).

GUIDED READING: the whole file is ONE function. Its shape, which you will meet in many programs:

    found = {}                      1. an empty "already seen" dictionary
    for folder in folders:          2. loop over the places to look
        if not a folder: continue      (skip what is not usable - `continue` = go to the next round)
        for entry in entries:       3. loop over what is inside
            if not an .app: continue
            if hidden or seen: continue
            found[key] = (name, path)   4. remember it
    return sorted(found.values())   5. return the result, sorted

Example:  find_apps(["/Applications", "~/Applications"], exclude=("terminal",))
          -> [("Obsidian", Path("/Applications/Obsidian.app")), ("Safari", Path("/Applications/Safari.app")), ...]
Try it:   python3 -c "import sys; sys.path.insert(0,'cli'); import myapps; print(myapps.find_apps(['/Applications'])[:3])"
It runs on every keystroke, so it must be quick: it reads one folder level only (no deep search).
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
    # Why a dict and not a list? `key in found` is instant even with thousands of entries, and assigning
    # `found[key] = ...` automatically keeps ONE entry per name. `exclude` holds lower-case names, so we compare lower-case.
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
            # Path pieces: Path("/Applications/Obsidian.app").suffix == ".app", .stem == "Obsidian", .name == "Obsidian.app".
            if entry.suffix.lower() != ".app" or not entry.is_dir():
                continue
            name = entry.stem  # "Obsidian.app" -> "Obsidian"
            key = name.lower()
            if key in exclude or key in found:
                continue
            found[key] = (name, entry)
    # `key=lambda pair: pair[0].lower()`: sort the (name, path) pairs by name, ignoring capitals.
    return sorted(found.values(), key=lambda pair: pair[0].lower())
