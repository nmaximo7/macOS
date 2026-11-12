"""
myexpander.py - use your Espanso snippets from the launcher.

Espanso is a text expander: you type a trigger such as  ;bsite  in any application and it writes
the long text for you. Its snippets live in .yml files (YAML), for example:

    matches:
      - trigger: ";bsite"
        replace: "https://justtothepoint.com/"
      - trigger: ";hcode"
        replace: "```\n$|$\n```"
      - triggers: [";mail", ";email"]
        replace: "me@example.com"
        label: "my address"

mylauncher does NOT replace text while you type (that is Espanso's job). It reads the same files and
lets you search the triggers in the launcher; Enter copies the text to the clipboard and shows a
notification. So your snippets are written in ONE place and both tools use them.

What we read
  * every .yml / .yaml file in the configured folder and ALL its subfolders (folders starting with a
    dot, like .git, are skipped);
  * in each file, the list under `matches`; each entry with `trigger` (or `triggers`, a list) and a
    plain-text `replace`.
What we skip (and count, so `ml doctor` can tell you)
  * entries with `vars` or `form` or `{{...}}` in the text (dates, clipboard, shell commands, forms):
    they need Espanso itself to be evaluated; `regex` triggers; entries without a text `replace`.
The cursor marker $|$ (where Espanso puts the cursor) is removed, because a clipboard has no cursor.

YAML is not part of Python's standard library, so this one module needs PyYAML (it is in
app/requirements.txt). If it is missing the launcher still works, just without snippets.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

CURSOR_MARKER = "$|$"
YAML_SUFFIXES = (".yml", ".yaml")


@dataclass(frozen=True)
class Snippet:
    trigger: str  # ";bsite"
    text: str  # what gets copied
    label: str = ""  # optional description from the file (searched too)
    source: str = ""  # file name, for messages


@dataclass
class Scan:
    """The result of reading the folder: the snippets, and everything we could not use (with why)."""

    snippets: list = field(default_factory=list)
    files: int = 0  # how many .yml files were read
    skipped: int = 0  # entries we ignore on purpose (variables, forms, regex...)
    duplicates: int = 0  # the same trigger twice: the first one wins
    problems: list = field(default_factory=list)  # ["file.yml: what went wrong"]
    missing_yaml: bool = False  # PyYAML is not installed


def find_yaml_files(folder: Path) -> list:
    """All .yml/.yaml files below `folder`, sorted, skipping folders that start with a dot."""
    found = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        found += [Path(root) / name for name in sorted(files) if name.lower().endswith(YAML_SUFFIXES) and not name.startswith(".")]
    return found


def yaml_loader():
    """Return a function text -> Python data, or None when PyYAML is not installed.

    CSafeLoader is the fast version (written in C) that comes with most PyYAML installs; "safe"
    means a file can never run code, only describe data.
    """
    try:
        import yaml
    except ImportError:
        return None
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    return lambda text: yaml.load(text, Loader=loader)  # noqa: S506  (safe loader)


def clean_text(text: str, strip_cursor: bool = True) -> str:
    return text.replace(CURSOR_MARKER, "") if strip_cursor else text


def parse_matches(data, source: str = "", strip_cursor: bool = True) -> tuple:
    """data = what the YAML file contained. Returns (snippets, skipped_count). Never raises."""
    if not isinstance(data, dict) or not isinstance(data.get("matches"), list):
        return [], 0  # not a snippets file (Espanso config files look like this): nothing to do, not an error
    snippets, skipped = [], 0
    for entry in data["matches"]:
        if not isinstance(entry, dict):
            skipped += 1
            continue
        triggers = entry.get("triggers", [entry.get("trigger")])
        triggers = [t for t in triggers if isinstance(t, str) and t.strip()] if isinstance(triggers, list) else []
        text = entry.get("replace")
        if isinstance(text, (int, float)) and not isinstance(text, bool):
            text = str(text)
        dynamic = "vars" in entry or "form" in entry or (isinstance(text, str) and "{{" in text)
        if not triggers or not isinstance(text, str) or dynamic:
            skipped += 1  # regex triggers, images, forms, variables...: Espanso itself is needed for these
            continue
        label = entry.get("label")
        label = label.strip() if isinstance(label, str) else ""
        for trigger in triggers:
            snippets.append(Snippet(trigger.strip(), clean_text(text, strip_cursor), label, source))
    return snippets, skipped


def load_snippets(folder, strip_cursor: bool = True, loader="default") -> Scan:
    """Read every YAML file below `folder`. A broken file is reported in scan.problems and skipped."""
    scan = Scan()
    folder = Path(folder)
    if not folder.is_dir():
        scan.problems.append(f"folder not found: {folder}")
        return scan
    load = yaml_loader() if loader == "default" else loader
    if load is None:
        scan.missing_yaml = True
        return scan
    seen = set()
    for path in find_yaml_files(folder):
        try:
            data = load(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - YAML errors, bad encoding, unreadable file: all just "skip it"
            first_line = (str(exc).strip().splitlines() or [type(exc).__name__])[0]
            scan.problems.append(f"{path.name}: {first_line}")
            continue
        scan.files += 1
        snippets, skipped = parse_matches(data, path.name, strip_cursor)
        scan.skipped += skipped
        for snippet in snippets:
            if snippet.trigger in seen:
                scan.duplicates += 1
                continue
            seen.add(snippet.trigger)
            scan.snippets.append(snippet)
    return scan


def preview(text: str, width: int = 70) -> str:
    """One short line for the list: lines joined with ⏎, cut at `width`."""
    line = " ⏎ ".join(part.strip() for part in text.strip().splitlines() if part.strip())
    return line if len(line) <= width else line[: width - 1].rstrip() + "…"
