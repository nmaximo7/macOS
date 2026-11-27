"""
myaerospace.py - when an application is launched, go to ITS workspace (AeroSpace, the tiling window manager).

Where does "Visual Studio Code -> workspace C" come from? From two places, in this order:
  1. the setting  aerospace.workspaces  of myconfiguration.json   {"Visual Studio Code": "C"}
  2. your aerospace.toml: the rules you already wrote there
         [[on-window-detected]]
         if.app-id = 'com.microsoft.VSCode'
         run = 'move-node-to-workspace C'
     (also  if.app-name-regex-substring = 'code'  works)
So you do not write the mapping twice: the launcher reads the one AeroSpace already uses.

What we do: `aerospace workspace C` FIRST, then `open -a App`. If the app is new, AeroSpace puts its window
on C (where you already are); if it is already running, `open` brings it to the front on C.
Everything here is optional: with aerospace.enabled = false, or no rule found, the app simply opens.

GUIDED TOUR: from the specific to the general.
  Rule              one `[[on-window-detected]]` rule reduced to (workspace, app_id, name_regex).
  find_command()    where is the `aerospace` program? The setting, then PATH (`shutil.which`), then the usual Homebrew places. Why the list?
                    A program started at LOGIN has a short PATH (no /opt/homebrew/bin), so "it works in my terminal" is not enough.
                    `next((x for x in places if exists(x)), "")` = the first place that exists, or "" - the idiom for "first match or default".
  read_rules()      aerospace.toml -> [Rule]. TOML again via tomllib (Python 3.11+; the `try: import tomllib / except ModuleNotFoundError`
                    at the top keeps older Pythons working, only without this feature).
                    The `run` line may be a string or a LIST of commands; the regular expression MOVE finds "move-node-to-workspace C"
                    (allowing options like --focus-follows-window) and captures the workspace name.
  bundle_id()       an application's identity: the file Contents/Info.plist (a "property list", Apple's settings format) holds
                    CFBundleIdentifier, e.g. "com.microsoft.VSCode". `plistlib` reads it (the file is binary: open with "rb").
  workspace_for()   the decision, in priority order: (1) your explicit setting by name, (2) a rule whose app-id equals the bundle id,
                    (3) a rule whose regular expression matches the app name. First hit wins; "" means "do not move".
                    A broken user-written regex (`re.error`) is skipped, not fatal.
  switch_command()  ["aerospace", "workspace", "C"]
`read_id=bundle_id` as a default parameter lets tests give a fake id reader (no real .app needed).
Try it:  ml run "code" --dry-run     (with a matching rule the dry run mentions the aerospace workspace switch before `open`; not tested on a Mac)
"""

from __future__ import annotations

import plistlib
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python older than 3.11
    tomllib = None

MOVE = re.compile(r"move-node-to-workspace\s+(?:--[\w-]+\s+)*([^\s;]+)")
KNOWN_PLACES = ("/opt/homebrew/bin/aerospace", "/usr/local/bin/aerospace", "/Applications/AeroSpace.app/Contents/MacOS/AeroSpace")


@dataclass(frozen=True)
class Rule:
    """One `[[on-window-detected]]` rule reduced to what we need."""

    workspace: str
    app_id: str = ""
    name_regex: str = ""


def find_command(command: str = "aerospace", which=shutil.which, exists=lambda p: Path(p).exists()) -> str:
    """The path of the aerospace program: the setting, then PATH, then the usual Homebrew places ('' = not found).

    A program started at login has a short PATH (no /opt/homebrew/bin), hence the list of places.
    """
    found = which(command)
    if found:
        return found
    if "/" in command and exists(command):
        return command
    return next((place for place in KNOWN_PLACES if exists(place)), "")


def read_rules(path) -> tuple:
    """([Rule], problem) from the `[[on-window-detected]]` rules of aerospace.toml."""
    if tomllib is None:
        return [], "needs Python 3.11 or newer (tomllib) to read aerospace.toml"
    path = Path(path).expanduser()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [], f"{path} does not exist"
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return [], f"cannot read {path}: {exc}"
    rules = []
    for entry in data.get("on-window-detected", []) or []:
        condition = entry.get("if", {}) if isinstance(entry.get("if"), dict) else {}
        run = entry.get("run", "")
        run = " ; ".join(run) if isinstance(run, list) else str(run)
        move = MOVE.search(run)
        app_id = condition.get("app-id") or entry.get("if.app-id") or ""
        name = condition.get("app-name-regex-substring") or entry.get("if.app-name-regex-substring") or ""
        if move and (app_id or name):
            rules.append(Rule(move.group(1), str(app_id), str(name)))
    return rules, ""


def bundle_id(app_path) -> str:
    """CFBundleIdentifier of an .app ('' if it cannot be read): "com.microsoft.VSCode"."""
    try:
        with open(Path(app_path) / "Contents" / "Info.plist", "rb") as handle:
            return str(plistlib.load(handle).get("CFBundleIdentifier", ""))
    except (OSError, plistlib.InvalidFileException, ValueError):
        return ""


def workspace_for(app_path, app_name: str, explicit: dict, rules: list, read_id=bundle_id) -> str:
    """The workspace of this application ('' = no idea, do not move)."""
    wanted = app_name.strip().lower()
    for name, workspace in explicit.items():
        if name.strip().lower() == wanted:
            return workspace
    app_id = read_id(app_path)
    for rule in rules:
        if rule.app_id and rule.app_id == app_id:
            return rule.workspace
    for rule in rules:
        if rule.name_regex:
            try:
                if re.search(rule.name_regex, app_name, re.I):
                    return rule.workspace
            except re.error:
                continue
    return ""


def switch_command(command: str, workspace: str) -> list:
    return [command, "workspace", workspace]
