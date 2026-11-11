"""
myconfig.py - read and CHECK conf/myconfiguration.json.

Rule of the project: every setting lives in ONE file, conf/myconfiguration.json. Nothing is
hidden in the code. This module is the only one that opens that file; everybody else receives a
ready-made `Config` object.

"Checking" matters: if you make a typo in the JSON (a missing comma, "comand" instead of
"command"), you get a message that says WHICH setting is wrong, instead of a mysterious crash
later.

Where is the file looked for? In this order (first hit wins):
  1. the option  --config /some/file.json        (given on the command line)
  2. the environment variable  MYLAUNCHER_CONF   (handy for experiments and tests)
  3. conf/myconfiguration.json next to the cli/ folder  (the normal case)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from myactions import COMMAND_ACTIONS

ENV_VAR = "MYLAUNCHER_CONF"
VALID_MODIFIERS = ("command", "shift", "control", "option")


class ConfigError(Exception):
    """The configuration file is missing or wrong. The message says what to fix."""


@dataclass(frozen=True)
class CommandDef:
    """A command written in the "commands" list of the configuration file."""

    id: str
    title: str
    action: str
    keywords: tuple
    confirm: bool


@dataclass(frozen=True)
class Config:
    """All the settings, checked and with the right types."""

    path: Path  # which file they came from
    hotkey_modifiers: tuple  # ("command",)   (used by the window, app/)
    hotkey_key: str  # "d"
    app_folders: tuple  # folders searched for *.app (already expanded: ~ becomes /Users/you)
    app_exclude: tuple  # app names to hide (lower case)
    max_results: int  # how many suggestions to show
    ignore_accents: bool  # True: "cafe" finds "Café"
    fuzzy: bool  # True: letters in order also match ("sfr" finds "Safari")
    commands: tuple  # tuple of CommandDef
    window_title: str = "mylauncher"  # title of the window
    window_width: int = 640  # width in pixels
    window_font_size: int = 20  # size of the letters
    window_top_offset: int = 160  # pixels between the top of the screen and the window
    autostart_label: str = "com.mylauncher.app"  # name of the launchd agent (and of its .plist file)
    autostart_log_dir: Path = Path("~/Library/Logs/mylauncher").expanduser()  # where the app writes its log
    autostart_keep_alive: bool = True  # launchd restarts the app if it crashes


# --------------------------------------------------------------------------- #
# Finding and reading the file                                                #
# --------------------------------------------------------------------------- #


def find_config_path(explicit: str | None = None, environ: dict | None = None) -> Path:
    """Decide which file to read (see the three rules in the module docstring)."""
    environ = os.environ if environ is None else environ
    if explicit:
        return Path(explicit).expanduser()
    if environ.get(ENV_VAR):
        return Path(environ[ENV_VAR]).expanduser()
    # __file__ is this file (cli/myconfig.py); .parent is cli/; .parent again is mylauncher/
    return Path(__file__).resolve().parent.parent / "conf" / "myconfiguration.json"


def load_config(path: Path) -> Config:
    """Read the JSON file, check every setting and return a Config. Raises ConfigError."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(f"configuration file not found: {path}") from None
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        # JSON is strict: no comments, no trailing commas. The line number helps a lot.
        raise ConfigError(f"{path} is not valid JSON (line {exc.lineno}, column {exc.colno}): {exc.msg}") from None
    return parse_config(data, path)


# --------------------------------------------------------------------------- #
# Checking the content                                                        #
# --------------------------------------------------------------------------- #


def _section(data: dict, name: str) -> dict:
    value = data.get(name)
    if not isinstance(value, dict):
        raise ConfigError(f'setting "{name}" must be an object {{ ... }}')
    return value


def _check(value, kind: type, where: str):
    """Return `value` if it has the right type, otherwise raise a clear error."""
    # bool is a kind of int in Python, so True would pass as a number: reject that explicitly.
    if kind is int and isinstance(value, bool):
        raise ConfigError(f'setting "{where}" must be a number')
    if not isinstance(value, kind):
        names = {str: "text", int: "a whole number", bool: "true or false", list: "a list [ ... ]"}
        raise ConfigError(f'setting "{where}" must be {names.get(kind, kind.__name__)}')
    return value


def _text_list(value, where: str) -> tuple:
    """A JSON list of texts -> a tuple of texts."""
    items = _check(value, list, where)
    for number, entry in enumerate(items):
        _check(entry, str, f"{where}[{number}]")
    return tuple(items)


def parse_config(data, path: Path) -> Config:
    """Turn the dictionary read from JSON into a checked Config."""
    if not isinstance(data, dict):
        raise ConfigError("the configuration must be a JSON object { ... }")

    # ---- hotkey -------------------------------------------------------------
    hotkey = _section(data, "hotkey")
    modifiers = tuple(m.lower() for m in _text_list(hotkey.get("modifiers"), "hotkey.modifiers"))
    for modifier in modifiers:
        if modifier not in VALID_MODIFIERS:
            raise ConfigError(f'hotkey.modifiers: "{modifier}" is not valid; use {", ".join(VALID_MODIFIERS)}')
    key = _check(hotkey.get("key"), str, "hotkey.key").lower()
    if len(key) != 1:
        raise ConfigError('hotkey.key must be ONE character, for example "d"')

    # ---- apps ---------------------------------------------------------------
    apps = _section(data, "apps")
    folders = tuple(Path(f).expanduser() for f in _text_list(apps.get("folders"), "apps.folders"))
    exclude = tuple(name.lower() for name in _text_list(apps.get("exclude", []), "apps.exclude"))

    # ---- search -------------------------------------------------------------
    search = _section(data, "search")
    max_results = _check(search.get("max_results"), int, "search.max_results")
    if max_results < 1:
        raise ConfigError('search.max_results must be at least 1')
    ignore_accents = _check(search.get("ignore_accents"), bool, "search.ignore_accents")
    fuzzy = _check(search.get("fuzzy"), bool, "search.fuzzy")

    # ---- commands -----------------------------------------------------------
    raw_commands = _check(data.get("commands"), list, "commands")
    commands, seen = [], set()
    for number, entry in enumerate(raw_commands):
        where = f"commands[{number}]"
        _check(entry, dict, where)
        command_id = _check(entry.get("id"), str, f"{where}.id")
        if command_id in seen:
            raise ConfigError(f'{where}.id: "{command_id}" is used twice; every id must be unique')
        seen.add(command_id)
        action = _check(entry.get("action"), str, f"{where}.action")
        if action not in COMMAND_ACTIONS:
            raise ConfigError(f'{where}.action: "{action}" is unknown; use one of: {", ".join(COMMAND_ACTIONS)}')
        commands.append(
            CommandDef(
                id=command_id,
                title=_check(entry.get("title"), str, f"{where}.title"),
                action=action,
                keywords=_text_list(entry.get("keywords", []), f"{where}.keywords"),
                confirm=_check(entry.get("confirm", False), bool, f"{where}.confirm"),
            )
        )

    # ---- window (optional: every value has a default) -----------------------
    window = data.get("window", {})
    _check(window, dict, "window")
    window_title = _check(window.get("title", "mylauncher"), str, "window.title")
    sizes = {}
    for name, default in (("width", 640), ("font_size", 20), ("top_offset", 160)):
        value = _check(window.get(name, default), int, f"window.{name}")
        if value < (0 if name == "top_offset" else 1):
            raise ConfigError(f"window.{name} is too small")
        sizes[name] = value

    # ---- autostart (optional: every value has a default) ---------------------
    autostart = data.get("autostart", {})
    _check(autostart, dict, "autostart")
    label = _check(autostart.get("label", "com.mylauncher.app"), str, "autostart.label")
    if not label or any(c in label for c in " /\\"):
        raise ConfigError('autostart.label must be a name without spaces or slashes, e.g. "com.mylauncher.app"')
    log_dir = Path(_check(autostart.get("log_dir", "~/Library/Logs/mylauncher"), str, "autostart.log_dir")).expanduser()
    keep_alive = _check(autostart.get("keep_alive", True), bool, "autostart.keep_alive")

    return Config(
        path=Path(path),
        hotkey_modifiers=modifiers,
        hotkey_key=key,
        app_folders=folders,
        app_exclude=exclude,
        max_results=max_results,
        ignore_accents=ignore_accents,
        fuzzy=fuzzy,
        commands=tuple(commands),
        window_title=window_title,
        window_width=sizes["width"],
        window_font_size=sizes["font_size"],
        window_top_offset=sizes["top_offset"],
        autostart_label=label,
        autostart_log_dir=log_dir,
        autostart_keep_alive=keep_alive,
    )
