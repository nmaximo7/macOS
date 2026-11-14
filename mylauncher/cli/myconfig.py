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
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from myactions import COMMAND_ACTIONS
from myedit import load_edit
from myexecute import DEFAULT_SHELL, DEFAULT_SOURCE, DEFAULT_TERMINAL_COMMAND, load_execute
from myquicklinks import load_quicklinks
from mytypes import ConfigError  # defined in mytypes.py; imported here so "from myconfig import ConfigError" keeps working

ENV_VAR = "MYLAUNCHER_CONF"
# The colours of the window (any #rrggbb). The names are the only ones allowed in window.colors.
DEFAULT_COLORS = {
    "background": "#1c1c1f",  # the window
    "input_background": "#26262b",  # the line where you type
    "text": "#f5f5f7",  # titles
    "muted": "#8e8e93",  # grey information (subtitles, labels)
    "selection": "#34343c",  # the highlighted row
    "command": "#ff9f0a",  # the word the launcher recognised (kill, yt, ;p ...)
}
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
VALID_MODIFIERS = ("command", "shift", "control", "option")


@dataclass(frozen=True)
class CommandDef:
    """A command written in the "commands" list of the configuration file."""

    id: str
    title: str
    action: str
    keywords: tuple
    confirm: bool
    icon: str = ""  # emoji shown in the list
    description: str = ""  # grey text under/after the title


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
    quicklinks_path: Path = Path("quicklinks.json")  # the web searches file (relative paths: next to this file)
    quicklinks: tuple = ()  # tuple of Quicklink, read from that file by load_config
    usage_enabled: bool = True  # remember how often each item is used
    usage_file: Path = Path("~/Library/Application Support/mylauncher/usage.json").expanduser()
    usage_boost_per_use: int = 2  # score points per use...
    usage_max_boost: int = 10  # ...but never more than this (must stay below 20: a better match always wins)
    kill_word: str = "kill"  # the word that starts the "close an app" mode
    kill_grace_seconds: int = 5  # how long to wait for an app to quit by itself
    kill_auto_force: bool = False  # True: force quit without asking when it did not quit
    kill_protected: tuple = ("python",)  # app names (lower case) that kill never lists
    menubar_enabled: bool = True  # show the icon in the menu bar
    menubar_title: str = "⌘"  # the text (or emoji) of that icon
    menubar_hide_dock: bool = False  # True: no Dock icon, menu bar only
    expander_enabled: bool = False  # True when expander.folder is set (and expander.enabled is not false)
    expander_folder: Path = Path("")  # where the Espanso .yml files are (searched in all subfolders)
    expander_strip_cursor: bool = True  # remove Espanso's cursor marker $|$ from the copied text
    expander_notify: bool = True  # show a macOS notification when a snippet is copied
    expander_group_length: int = 2  # ";pclarify" belongs to the group ";p" (this many first characters)
    expander_groups: dict = field(default_factory=dict)  # {";p": ("bookmark", "🔖")} names/icons of the groups
    hotkey_swallow: bool = True  # True: the application in front does not receive the hotkey
    run_word: str = "run"  # the word that lists all the applications
    max_browse_results: int = 100  # how many rows "run", "kill" and ";" lists may have (the window scrolls)
    window_font: str = "Helvetica Neue"
    window_style: str = "borderless"  # "borderless": no title bar buttons; "standard": a normal window
    window_colors: dict = field(default_factory=lambda: dict(DEFAULT_COLORS))
    help_word: str = "help"  # the word that opens the help topics
    help_aliases_file: Path = Path("~/.zsh_aliases").expanduser()  # comments above each alias are read from here
    help_functions_file: Path = Path("~/.zsh_functions").expanduser()
    help_aerospace_config: Path = Path("~/.config/aerospace/aerospace.toml").expanduser()
    help_skills_folder: Path = Path("~/macOS/claude/skills").expanduser()
    help_script: Path = Path("~/macOS/scripts/help.sh").expanduser()  # holds the sec_<name>() cheat sheets
    help_scripts_folder: Path = Path("~/macOS/scripts").expanduser()
    help_cache_seconds: int = 600  # how long the slow answers (aliases, system) are remembered; 0 = never
    help_cache_file: Path = Path("~/Library/Application Support/mylauncher/help-cache.json").expanduser()
    edit_word: str = "edit"  # the word that lists the files of edit.json
    edit_path: Path = Path("edit.json")  # relative paths: next to myconfiguration.json
    edit_entries: tuple = ()  # tuple of EditEntry, read from that file by load_config
    edit_editor: tuple = ("open", "-a", "Visual Studio Code", "{path}")  # {path} is replaced by the file
    execute_word: str = "execute"
    execute_path: Path = Path("execute.json")
    execute_entries: tuple = ()  # tuple of ExecEntry
    execute_shell: tuple = DEFAULT_SHELL  # runs "<shell> <script>"
    execute_source: tuple = DEFAULT_SOURCE  # files loaded before every command (your zsh functions)
    execute_terminal: bool = False  # default for entries that do not say "terminal": true/false
    execute_terminal_command: tuple = DEFAULT_TERMINAL_COMMAND  # {command} is replaced by the script
    execute_log_dir: Path = Path("~/Library/Logs/mylauncher/execute").expanduser()
    execute_notify: bool = True  # background commands: a notification says how they ended
    browser_command: tuple = ()  # how to open a web address, with {url}; empty = the macOS default (open)


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
    config = parse_config(data, path)
    # The quicklinks live in their own file (conf/quicklinks.json); the keyword of the "kill" mode is reserved.
    reserved = (config.kill_word, config.run_word, config.help_word, config.edit_word, config.execute_word)
    links = load_quicklinks(config.quicklinks_path, reserved=reserved)
    return replace(
        config, quicklinks=links, edit_entries=load_edit(config.edit_path), execute_entries=load_execute(config.execute_path)
    )


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

    hotkey_swallow = _check(hotkey.get("swallow", True), bool, "hotkey.swallow")

    # ---- apps ---------------------------------------------------------------
    apps = _section(data, "apps")
    run_word = _check(apps.get("word", "run"), str, "apps.word").lower()
    if not run_word or len(run_word.split()) != 1:
        raise ConfigError('apps.word must be ONE word, for example "run"')
    folders = tuple(Path(f).expanduser() for f in _text_list(apps.get("folders"), "apps.folders"))
    exclude = tuple(name.lower() for name in _text_list(apps.get("exclude", []), "apps.exclude"))

    # ---- search -------------------------------------------------------------
    search = _section(data, "search")
    max_results = _check(search.get("max_results"), int, "search.max_results")
    if max_results < 1:
        raise ConfigError('search.max_results must be at least 1')
    ignore_accents = _check(search.get("ignore_accents"), bool, "search.ignore_accents")
    fuzzy = _check(search.get("fuzzy"), bool, "search.fuzzy")
    max_browse = _check(search.get("max_browse_results", 100), int, "search.max_browse_results")
    if max_browse < 1:
        raise ConfigError("search.max_browse_results must be at least 1")

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
                icon=_check(entry.get("icon", ""), str, f"{where}.icon").strip(),
                description=_check(entry.get("description", ""), str, f"{where}.description").strip(),
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
    font = _check(window.get("font", "Helvetica Neue"), str, "window.font")
    style = _check(window.get("style", "borderless"), str, "window.style")
    if style not in ("borderless", "standard"):
        raise ConfigError('window.style must be "borderless" or "standard"')
    colors = dict(DEFAULT_COLORS)
    given = _check(window.get("colors", {}), dict, "window.colors")
    for name, value in given.items():
        if name not in DEFAULT_COLORS:
            raise ConfigError(f'window.colors.{name} is not a colour of the window; use: {", ".join(DEFAULT_COLORS)}')
        if not isinstance(value, str) or not HEX_COLOR.match(value):
            raise ConfigError(f'window.colors.{name} must look like "#ff9f0a" (a # and six hexadecimal digits)')
        colors[name] = value

    # ---- autostart (optional: every value has a default) ---------------------
    autostart = data.get("autostart", {})
    _check(autostart, dict, "autostart")
    label = _check(autostart.get("label", "com.mylauncher.app"), str, "autostart.label")
    if not label or any(c in label for c in " /\\"):
        raise ConfigError('autostart.label must be a name without spaces or slashes, e.g. "com.mylauncher.app"')
    log_dir = Path(_check(autostart.get("log_dir", "~/Library/Logs/mylauncher"), str, "autostart.log_dir")).expanduser()
    keep_alive = _check(autostart.get("keep_alive", True), bool, "autostart.keep_alive")

    # ---- quicklinks, usage, kill, menubar (all optional: every value has a default) --
    quick = data.get("quicklinks", {})
    _check(quick, dict, "quicklinks")
    quick_file = Path(_check(quick.get("file", "quicklinks.json"), str, "quicklinks.file")).expanduser()
    if not quick_file.is_absolute():
        quick_file = Path(path).parent / quick_file  # relative: next to myconfiguration.json

    usage = data.get("usage", {})
    _check(usage, dict, "usage")
    usage_enabled = _check(usage.get("enabled", True), bool, "usage.enabled")
    usage_file = Path(_check(usage.get("file", "~/Library/Application Support/mylauncher/usage.json"), str, "usage.file")).expanduser()
    boost = _check(usage.get("boost_per_use", 2), int, "usage.boost_per_use")
    max_boost = _check(usage.get("max_boost", 10), int, "usage.max_boost")
    if boost < 0 or not 0 <= max_boost < 20:
        raise ConfigError("usage.boost_per_use must be 0 or more and usage.max_boost between 0 and 19 (a better match must always win)")

    kill = data.get("kill", {})
    _check(kill, dict, "kill")
    kill_word = _check(kill.get("word", "kill"), str, "kill.word").lower()
    if not kill_word or len(kill_word.split()) != 1:
        raise ConfigError('kill.word must be ONE word, for example "kill"')
    grace = _check(kill.get("grace_seconds", 5), int, "kill.grace_seconds")
    if grace < 0:
        raise ConfigError("kill.grace_seconds cannot be negative")
    auto_force = _check(kill.get("auto_force", False), bool, "kill.auto_force")
    protected = tuple(name.lower() for name in _text_list(kill.get("protected", ["python"]), "kill.protected"))

    menubar = data.get("menubar", {})
    _check(menubar, dict, "menubar")
    menubar_enabled = _check(menubar.get("enabled", True), bool, "menubar.enabled")
    menubar_title = _check(menubar.get("title", "⌘"), str, "menubar.title")
    menubar_hide_dock = _check(menubar.get("hide_dock_icon", False), bool, "menubar.hide_dock_icon")

    expander = data.get("expander", {})
    _check(expander, dict, "expander")
    folder_text = _check(expander.get("folder", ""), str, "expander.folder")
    expander_folder = Path(folder_text).expanduser() if folder_text.strip() else Path("")
    expander_enabled = _check(expander.get("enabled", True), bool, "expander.enabled") and bool(folder_text.strip())
    strip_cursor = _check(expander.get("strip_cursor_marker", True), bool, "expander.strip_cursor_marker")
    notify = _check(expander.get("notification", True), bool, "expander.notification")

    group_length = _check(expander.get("group_length", 2), int, "expander.group_length")
    if group_length < 2:
        raise ConfigError("expander.group_length must be at least 2 (the prefix character and one letter)")
    groups = {}
    for prefix, value in _check(expander.get("groups", {}), dict, "expander.groups").items():
        where = f"expander.groups[{prefix!r}]"
        if not prefix.strip() or any(c.isspace() for c in prefix):
            raise ConfigError(f"{where}: the group must be a trigger prefix without spaces, for example \";p\"")
        if isinstance(value, str):
            value = {"name": value}
        _check(value, dict, where)
        groups[prefix] = (_check(value.get("name", ""), str, f"{where}.name").strip(), _check(value.get("icon", ""), str, f"{where}.icon").strip())

    browser = data.get("browser", {})
    _check(browser, dict, "browser")
    browser_command = tuple(_text_list(browser.get("command", []), "browser.command"))
    if browser_command and not any("{url}" in part for part in browser_command):
        raise ConfigError('browser.command must contain "{url}" where the web address goes')

    help_section = data.get("help", {})
    _check(help_section, dict, "help")
    help_word = _check(help_section.get("word", "help"), str, "help.word").lower()
    if not help_word or len(help_word.split()) != 1:
        raise ConfigError('help.word must be ONE word, for example "help"')
    edit_section = data.get("edit", {})
    _check(edit_section, dict, "edit")
    edit_word = _check(edit_section.get("word", "edit"), str, "edit.word").lower()
    edit_file = Path(_check(edit_section.get("file", "edit.json"), str, "edit.file")).expanduser()
    if not edit_file.is_absolute():
        edit_file = Path(path).parent / edit_file
    editor = edit_section.get("editor", "Visual Studio Code")
    if isinstance(editor, str) and editor.strip():  # an application name: opened with `open -a`
        editor_command = ("open", "-a", editor.strip(), "{path}")
    else:
        editor_command = tuple(_text_list(editor, "edit.editor"))
        if not editor_command or not any("{path}" in part for part in editor_command):
            raise ConfigError('edit.editor must be an application name ("TextEdit") or a command list containing "{path}", for example ["nvim", "{path}"]')

    exec_section = data.get("execute", {})
    _check(exec_section, dict, "execute")
    execute_word = _check(exec_section.get("word", "execute"), str, "execute.word").lower()
    exec_file = Path(_check(exec_section.get("file", "execute.json"), str, "execute.file")).expanduser()
    if not exec_file.is_absolute():
        exec_file = Path(path).parent / exec_file
    exec_shell = tuple(_text_list(exec_section.get("shell", list(DEFAULT_SHELL)), "execute.shell"))
    if not exec_shell:
        raise ConfigError('execute.shell cannot be empty, for example ["/bin/zsh", "-lc"]')
    exec_source = tuple(_text_list(exec_section.get("source", list(DEFAULT_SOURCE)), "execute.source"))
    exec_terminal = _check(exec_section.get("terminal", False), bool, "execute.terminal")
    terminal_command = tuple(_text_list(exec_section.get("terminal_command", list(DEFAULT_TERMINAL_COMMAND)), "execute.terminal_command"))
    if not any("{command}" in part for part in terminal_command):
        raise ConfigError('execute.terminal_command must contain "{command}" where the script goes')
    exec_log_dir = Path(_check(exec_section.get("log_dir", "~/Library/Logs/mylauncher/execute"), str, "execute.log_dir")).expanduser()
    exec_notify = _check(exec_section.get("notify", True), bool, "execute.notify")

    words = [run_word, kill_word, help_word, edit_word, execute_word]
    for word_name, word in (("edit.word", edit_word), ("execute.word", execute_word)):
        if not word or len(word.split()) != 1:
            raise ConfigError(f"{word_name} must be ONE word")
    if len(set(words)) != len(words):
        raise ConfigError("apps.word, kill.word, help.word, edit.word and execute.word must all be different words")
    defaults = Config.__dataclass_fields__
    help_paths = {}
    for setting, field_name in (("aliases_file", "help_aliases_file"), ("functions_file", "help_functions_file"),
                            ("aerospace_config", "help_aerospace_config"), ("skills_folder", "help_skills_folder"),
                            ("help_script", "help_script"), ("scripts_folder", "help_scripts_folder"),
                            ("cache_file", "help_cache_file")):
        text = _check(help_section.get(setting, str(defaults[field_name].default)), str, f"help.{setting}")
        help_paths[field_name] = Path(text).expanduser()
    cache_seconds = _check(help_section.get("cache_seconds", 600), int, "help.cache_seconds")
    if cache_seconds < 0:
        raise ConfigError("help.cache_seconds cannot be negative (0 = do not remember)")

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
        quicklinks_path=quick_file,
        usage_enabled=usage_enabled,
        usage_file=usage_file,
        usage_boost_per_use=boost,
        usage_max_boost=max_boost,
        kill_word=kill_word,
        kill_grace_seconds=grace,
        kill_auto_force=auto_force,
        kill_protected=protected,
        menubar_enabled=menubar_enabled,
        menubar_title=menubar_title,
        menubar_hide_dock=menubar_hide_dock,
        expander_enabled=expander_enabled,
        expander_folder=expander_folder,
        expander_strip_cursor=strip_cursor,
        expander_notify=notify,
        expander_group_length=group_length,
        expander_groups=groups,
        hotkey_swallow=hotkey_swallow,
        run_word=run_word,
        max_browse_results=max_browse,
        window_font=font,
        window_style=style,
        window_colors=colors,
        browser_command=browser_command,
        help_word=help_word,
        edit_word=edit_word,
        edit_path=edit_file,
        edit_editor=editor_command,
        execute_word=execute_word,
        execute_path=exec_file,
        execute_shell=exec_shell,
        execute_source=exec_source,
        execute_terminal=exec_terminal,
        execute_terminal_command=terminal_command,
        execute_log_dir=exec_log_dir,
        execute_notify=exec_notify,
        help_cache_seconds=cache_seconds,
        **help_paths,
    )
