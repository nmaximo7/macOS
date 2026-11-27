"""
myespanso.py - keep Espanso OUT of the launcher window.

THE PROBLEM. You type a trigger (";pmath") in the launcher to find it. Espanso, running all the time, sees
those keys too and EXPANDS the trigger inside the launcher: it types (or pastes) the whole text, replaces
the clipboard and restores it afterwards, and floods the keyboard with events. Long texts made the copy
unreliable and made macOS switch the hotkey (Command+D) off.

THE FIX. Espanso accepts one config file per application. This one switches Espanso off for the window
whose title is the launcher's title:

    <espanso folder>/config/mylauncher.yml

GUIDED READING: four small functions around one idea - generate a tiny config file and put it where Espanso looks.
  config_text()   the YAML text. `filter_title` is a regular expression matched against the window title; `^...$` = the WHOLE title,
                  `re.escape` makes characters like ( or . literal, and ' is doubled because YAML single-quoted strings escape it that way.
                  `enable: false` = switch Espanso off for that window.
  config_dir()    find Espanso's config folder starting from the snippets folder and looking at it and its parents
                  (`(folder, *folder.parents)` = the folder first, then each ancestor up to the root).
  status()        the check `ml doctor` shows: is the file there and does it name our window?  Returns (ok, message).
  install()       write the file. Returns (ok, message) - never raises: a read-only folder becomes a message.
The (ok, message) pair is this project's usual way to report a result without exceptions. Try:  ml espanso-config   then   ml doctor
"""

from __future__ import annotations

import re
from pathlib import Path

FILE_NAME = "mylauncher.yml"


def config_text(window_title: str) -> str:
    """The YAML of the per-application Espanso config (the title is matched as a regular expression)."""
    return (
        "# Written by `ml espanso-config --install` (mylauncher).\n"
        "# Espanso must NOT expand triggers inside the launcher window: you type them there to FIND them.\n"
        "filter_title: '^" + re.escape(window_title).replace("'", "''") + "$'\n"
        "enable: false\n"
    )


def config_dir(snippets_folder) -> Path | None:
    """Espanso's `config` folder, found from the folder of the snippets (…/espanso/match). None if not found."""
    folder = Path(snippets_folder).expanduser()
    for candidate in (folder, *folder.parents):
        if (candidate / "config").is_dir():
            return candidate / "config"
        if candidate.name == "match":
            return candidate.parent / "config"
        if candidate.name == "espanso":
            return candidate / "config"
    return None


def status(snippets_folder, window_title: str) -> tuple:
    """(ok, message) for `ml doctor`: is there a file that switches Espanso off in the launcher window?"""
    folder = config_dir(snippets_folder)
    if folder is None:
        return False, "espanso: could not find Espanso's config folder next to the snippets; run  ml espanso-config"
    target = folder / FILE_NAME
    if not target.is_file():
        return False, f"espanso: it will EXPAND triggers typed in the launcher (long texts break, the hotkey may stop); fix:  ml espanso-config --install"
    try:
        wanted = re.escape(window_title)
        if wanted not in target.read_text(encoding="utf-8"):
            return False, f"espanso: {target} does not name the window title {window_title!r}; run  ml espanso-config --install"
    except OSError as exc:
        return False, f"espanso: cannot read {target}: {exc}"
    return True, f"espanso: switched off inside the launcher window ({target})"


def install(snippets_folder, window_title: str) -> tuple:
    """Write the file. Returns (ok, message)."""
    folder = config_dir(snippets_folder)
    if folder is None:
        return False, "could not find Espanso's config folder; create the file by hand (see `ml espanso-config`)"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / FILE_NAME
        target.write_text(config_text(window_title), encoding="utf-8")
    except OSError as exc:
        return False, f"could not write {folder / FILE_NAME}: {exc}"
    return True, f"written {target}  (Espanso reloads it by itself; if not: espanso restart)"
