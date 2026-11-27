"""
myedit.py - files you can open in your text editor from the launcher: conf/edit.json.

The file is a list. Each entry says WHAT to edit:

    [
      {"description": "AeroSpace, an i3-like tiling window manager",
       "emoji": "🪟",
       "path": "~/macOS/aerospace/.config/aerospace/aerospace.toml"},
      {"description": "skills, OpenClaw skills (SKILL.md)", "emoji": "🧠", "path": "~/macOS/claude/skills/**/SKILL.md"}
    ]

  description  free text. The words before the first comma are the NAME you search for and see as the title
               ("AeroSpace"); the rest is shown in grey. A description without a comma is both.
  name         optional: say the name explicitly instead of taking it from the description.
  emoji        optional: shown at the start of the row (default 📝).
  path         the file (or folder) to open. `~` works. A path with a wildcard (`*`, `?`, `[ ]`, and `**`
               for "any folders") means MANY files: one row for each file that exists now. Files and
               folders whose name starts with a dot are skipped.

How you use it:   edit   (then Space)   aero   (then Enter)  ->  the file opens in the editor of
`edit.editor` in conf/myconfiguration.json.

GUIDED TOUR: the file has the same shape as myquicklinks.py (chapter 7) - a frozen dataclass, a parser that checks, a loader - plus
one new idea, WILDCARDS.
  EditEntry                one entry of edit.json.
  split_description()      "AeroSpace, a tiling window manager" -> ("AeroSpace", "a tiling window manager"): the words before the first
                           comma are the NAME you search for; the rest is shown in grey. (`str.partition(",")` again.)
  parse_text_field()       the checks shared with execute.json (description/name/emoji), in ONE place: "don't repeat yourself".
  parse_edit(), load_edit()  check the data; read the file (a missing file = nothing to edit).
  tidy()                   /Users/me/x -> ~/x
  expand()                 ONE entry -> the files it stands for. Without wildcards: just the path. With `*`, `?`, `[ ]` or `**`:
                           whatever matches NOW (the list is rebuilt each time, so a new SKILL.md appears without any setting change).
  build_edit_items()       entries -> the rows (Items) the window shows; a missing file gets the badge "Missing" instead of failing.
Wildcard crib:  *  any characters in one folder name   ?  one character   **  any number of folders   [ab]  a or b
Example:  "~/macOS/claude/skills/**/SKILL.md"  ->  one row per skill, titled by the folder name (because "SKILL.md" says nothing).
"""

from __future__ import annotations

import glob
import json
from dataclasses import dataclass
from pathlib import Path

from mytypes import ConfigError, Item

WILDCARDS = "*?["


@dataclass(frozen=True)
class EditEntry:
    name: str
    description: str  # the grey part (what is left of the description after the name)
    emoji: str
    path: str  # as written in the file (with ~ and wildcards)


def split_description(description: str) -> tuple:
    """"AeroSpace, an i3-like tiling window manager" -> ("AeroSpace", "an i3-like tiling window manager")."""
    name, comma, rest = description.partition(",")
    return (name.strip(), rest.strip()) if comma else (description.strip(), "")


# NOTE the loop `for field, value in (("description", description), ...)`: a small TABLE of (name, value) pairs checked by one block of
# code. Three near-identical `if` blocks become one. (`field` is just a variable name here, not the dataclasses function.)
def parse_text_field(entry: dict, here: str) -> tuple:
    """Shared by edit.json and execute.json: (name, description, emoji) with the checks."""
    description = entry.get("description", "")
    name = entry.get("name", "")
    emoji = entry.get("emoji", "")
    for field, value in (("description", description), ("name", name), ("emoji", emoji)):
        if not isinstance(value, str):
            raise ConfigError(f"{here}.{field} must be text")
    if name.strip():
        shown_description = description.strip()
    else:
        name, shown_description = split_description(description)
    if not name:
        raise ConfigError(f'{here} needs a description (its first words are the name you search for), for example "AeroSpace, a tiling window manager"')
    return name.strip(), shown_description, emoji.strip()


def parse_edit(data, where: str = "edit.json") -> tuple:
    if not isinstance(data, list):
        raise ConfigError(f"{where} must be a list [ {{...}}, {{...}} ]")
    entries = []
    for number, entry in enumerate(data):
        here = f"{where}[{number}]"
        if not isinstance(entry, dict):
            raise ConfigError(f"{here} must be an object with a description and a path")
        name, description, emoji = parse_text_field(entry, here)
        path = entry.get("path")
        if not isinstance(path, str) or not path.strip():
            raise ConfigError(f'{here}.path must be text, for example "~/.zshrc"')
        entries.append(EditEntry(name, description, emoji, path.strip()))
    return tuple(entries)


def load_edit(path) -> tuple:
    """Read conf/edit.json. A missing file means "nothing to edit" (it is optional)."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ()
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON (line {exc.lineno}, column {exc.colno}): {exc.msg}") from None
    return parse_edit(data, path.name)


def tidy(path: Path) -> str:
    """/Users/me/x -> ~/x (shorter to read)."""
    home = str(Path.home())
    text = str(path)
    return "~" + text[len(home):] if text == home or text.startswith(home + "/") else text


def expand(entry: EditEntry) -> list:
    """[(label, Path)] this entry stands for. Without wildcards: the path itself (even if it does not exist yet,
    the row then says so). With wildcards: the files that exist now, sorted, hidden ones skipped."""
    # Algorithm: (1) no wildcard -> the path as it is. (2) else find the first wildcard character, take everything BEFORE it as the
    # fixed "base" folder, let glob (recursive=True makes ** work) list the matches, drop any whose path (relative to base) has a
    # part starting with "." (hidden), and give each a label (the file name, or the folder name for SKILL.md).
    pattern = str(Path(entry.path).expanduser())
    if not any(c in pattern for c in WILDCARDS):
        return [("", Path(pattern))]
    first_wildcard = min(pattern.index(c) for c in WILDCARDS if c in pattern)
    base = Path(pattern[:first_wildcard]).parent if "/" in pattern[:first_wildcard] else Path(".")
    found = []
    for name in sorted(glob.glob(pattern, recursive=True)):
        path = Path(name)
        try:
            parts = path.relative_to(base).parts
        except ValueError:
            parts = path.parts
        if any(p.startswith(".") for p in parts):
            continue
        # "SKILL.md" says nothing: the folder is the skill's name.
        found.append((path.parent.name if path.name == "SKILL.md" else path.name, path))
    return found


def build_edit_items(config) -> list:
    items = []
    for entry in config.edit_entries:
        for label, path in expand(entry):
            exists = path.exists()
            where = tidy(path) + ("" if exists else "  (not found)")
            subtitle = f"{entry.description}  ·  {where}" if entry.description else where
            items.append(
                Item(
                    id=f"edit:{entry.name}:{path}",
                    title=f"{entry.name} · {label}" if label else entry.name,
                    kind="edit",
                    action="edit_file",
                    target=str(path),
                    complete=f"{config.edit_word} {entry.name} · {label}" if label else f"{config.edit_word} {entry.name}",  # what Tab writes
                    keywords=tuple(k for k in (entry.description, str(path), label) if k),
                    subtitle=subtitle,
                    icon=entry.emoji,
                    badge="File" if exists else "Missing",
                )
            )
    return items
