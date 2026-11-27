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
  * entries with `vars` or `form` or a variable like `{{name}}` in the text (dates, clipboard, shell commands, forms):
    they need Espanso itself to be evaluated. Hugo shortcodes (`{{% pborder %}}`, `{{< figure >}}`) are NOT variables: they are kept; `regex` triggers; entries without a text `replace`.
The cursor marker $|$ (where Espanso puts the cursor) is removed, because a clipboard has no cursor.

YAML is not part of Python's standard library, so this one module needs PyYAML (it is in
app/requirements.txt). If it is missing the launcher still works, just without snippets.

GUIDED TOUR (top to bottom) ----------------------------------------------------------------------------------------------------
  Snippet / Scan          the shapes: ONE usable snippet, and the REPORT of a whole scan (snippets + everything skipped, and why).
  find_yaml_files()       walk the folder tree and list the .yml/.yaml files.
  yaml_loader()           a function text -> data, or None if PyYAML is missing (so the launcher still works without it).
  parse_matches()         ONE file's data -> snippets. The heart of the file. NEVER raises: a strange entry is counted and skipped.
  load_snippets()         the whole folder: files -> parse_matches -> remove duplicate triggers -> a Scan.
  preview(), group_of(), describe_groups()   presentation helpers (one-line preview; ";p" groups like ";p" = prompts).

THE DESIGN RULE: "be liberal in what you read". Your snippet folder is also Espanso's, written for another program. We only take what we
fully understand (a trigger and a plain-text replace) and COUNT the rest, with the reason, so `ml doctor` can say "12 skipped: has {{...}}".
We never guess (a snippet with a clipboard variable would copy the literal text "{{clipboard}}", which is worse than not offering it).
Example of ONE entry becoming ONE Snippet:

    - trigger: ";bsite"                 ->   Snippet(trigger=";bsite", text="https://justtothepoint.com/", label="", source="bookmark.yml")
      replace: "https://justtothepoint.com/"
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

CURSOR_MARKER = "$|$"
# An Espanso VARIABLE looks like {{name}} (letters, digits, _ or .). Hugo shortcodes look like {{% pborder %}} or {{< figure >}}:
# they are plain text for Espanso and must be copied as they are (before, any "{{" made the snippet "dynamic" and it was skipped).
VARIABLE = re.compile(r"\{\{\s*[\w.]+\s*\}\}")
YAML_SUFFIXES = (".yml", ".yaml")


@dataclass(frozen=True)
class Snippet:
    trigger: str  # ";bsite"
    text: str  # what gets copied
    label: str = ""  # optional description from the file (searched too)
    source: str = ""  # file name, for messages


# Scan is NOT frozen: we fill it in while we scan (scan.skipped += 1). `field(default_factory=list)` gives every Scan its OWN empty
# list. (Writing `snippets: list = []` would share ONE list between all Scans: a classic Python trap, which dataclasses refuse.)
@dataclass
class Scan:
    """The result of reading the folder: the snippets, and everything we could not use (with why)."""

    snippets: list = field(default_factory=list)
    files: int = 0  # how many .yml files were read
    skipped_notes: list = field(default_factory=list)  # ["file.yml ;trigger: has {{...}}"], so you can see WHICH ones
    skipped: int = 0  # entries we ignore on purpose (variables, forms, regex...)
    duplicates: int = 0  # the same trigger twice: the first one wins
    problems: list = field(default_factory=list)  # ["file.yml: what went wrong"]
    missing_yaml: bool = False  # PyYAML is not installed


def find_yaml_files(folder: Path) -> list:
    """All .yml/.yaml files below `folder`, sorted, skipping folders that start with a dot."""
    found = []
    # os.walk visits the folder, then each sub-folder... `dirs[:] = ...` edits the list IN PLACE: os.walk then only descends into the
    # folders we kept (so ".git" is never entered) and in sorted order (the same result on every Mac).
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
    # getattr(obj, "name", default): the attribute if it exists, else the default (not every install has the fast C version).
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    return lambda text: yaml.load(text, Loader=loader)  # noqa: S506  (safe loader)


def clean_text(text: str, strip_cursor: bool = True) -> str:
    return text.replace(CURSOR_MARKER, "") if strip_cursor else text


def parse_matches(data, source: str = "", strip_cursor: bool = True, notes: list | None = None) -> tuple:
    """data = what the YAML file contained. Returns (snippets, skipped_count). Never raises.

    For each entry of `matches:` the steps are (read the code with this list beside it):
      1. is it a dict? (else skip)                      2. triggers: `triggers: [..]` or a single `trigger:` -> a clean list of texts
      3. text = `replace` (a bare number like 42 becomes "42")
      4. "dynamic"? = has `vars`, `form`, or a {{variable}} in the text -> Espanso must evaluate it -> skip, and WRITE DOWN why
      5. otherwise ONE Snippet per trigger (an entry with two triggers gives two snippets with the same text).
    `isinstance(x, (int, float)) and not isinstance(x, bool)`: in Python True is an int (True == 1), so we must exclude booleans by hand.
    """
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
        dynamic = "vars" in entry or "form" in entry or (isinstance(text, str) and VARIABLE.search(text) is not None)
        if not triggers or not isinstance(text, str) or dynamic:
            skipped += 1  # regex triggers, images, forms, variables...: Espanso itself is needed for these
            if notes is not None:
                name = (triggers or [str(entry.get("regex") or entry.get("trigger") or "?")])[0]
                why = "no trigger/text" if not triggers or not isinstance(text, str) else ("vars/form" if "vars" in entry or "form" in entry else "has {{...}} in the text")
                notes.append(f"{source} {name}: {why}")
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
    seen = set()  # triggers already taken: the FIRST file (in sorted order) wins, later duplicates are only counted
    for path in find_yaml_files(folder):
        try:
            data = load(path.read_text(encoding="utf-8"))
        # One bad file must not hide all the others, so we catch broadly here (and report the first line of the error).
        except Exception as exc:  # noqa: BLE001 - YAML errors, bad encoding, unreadable file: all just "skip it"
            first_line = (str(exc).strip().splitlines() or [type(exc).__name__])[0]
            scan.problems.append(f"{path.name}: {first_line}")
            continue
        scan.files += 1
        snippets, skipped = parse_matches(data, path.name, strip_cursor, scan.skipped_notes)
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


def group_of(trigger: str, length: int) -> str:
    """";pclarify" -> ";p" (the first `length` characters: the prefix character and the first letter)."""
    return trigger[:length]


def describe_groups(snippets, length: int, configured: dict) -> dict:
    """{";p": (name, icon, count)} for every group.

    The name comes from the configuration (expander.groups) when given; otherwise from the file the
    group's snippets mostly live in ("bookmark.yml" -> "bookmark"), because people usually keep one
    topic per file. The icon is only what the configuration says (empty = the default).
    """
    # `dict.setdefault(key, [])` returns the list for that key, creating an empty one the first time: a short way to GROUP things.
    # `max(set(stems), key=stems.count)` = the most frequent file name (the "mode"): the group is named after where it mostly lives.
    members: dict = {}
    for snippet in snippets:
        members.setdefault(group_of(snippet.trigger, length), []).append(snippet)
    groups = {}
    for prefix, items in members.items():
        name, icon = configured.get(prefix, ("", ""))
        if not name:
            stems = [Path(s.source).stem for s in items if s.source]
            name = max(set(stems), key=stems.count) if stems else ""
        groups[prefix] = (name, icon, len(items))
    return groups
