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
from mynotify import METHODS as NOTIFY_METHODS
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


BRIEFING_DEFAULTS = {
    "gog": "gog",
    "qmd": "qmd",
    "calendar_days": 8,
    "mail_query": "in:inbox",
    "mail_limit": 8,
    "todo_file": "$HOME/macOS/docs/assets/Todo.md",
    "max_chars": 20000,
    "save_folder": "",
}


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
    expander_paste: bool = True  # after copying a snippet, press Command+V in the application you came from (what Espanso did)
    expander_paste_delay_ms: int = 250
    expander_notify: bool = True  # show a macOS notification when a snippet is copied
    expander_copy_log: Path | None = Path("~/Library/Logs/mylauncher/copy.log").expanduser()  # one line per copy ("" = no log)
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
    secret_word: str = "secret"  # lists the secrets (values hidden)
    secret_edit_word: str = "keep_secret"  # opens the secret file in the editor
    secret_file: Path = Path("~/.config/mylauncher/secrets.env").expanduser()  # outside the repository!
    secret_clear_seconds: int = 30  # the clipboard is emptied this long after copying a secret (0 = never)
    secret_service: str = "justtothepoint-toolkit"  # Keychain service name (the one openrouter.py --set-key uses)
    secret_input_echo: str = "hidden"  # ml secret-set: "hidden" (nothing shown), "asterisks" (*****) or "visible" (the characters)
    secret_notify_value: bool = True  # the notification after copying a secret shows the value
    secret_reveal: int = 4  # how many last characters of a value stay visible in the list (0 = none)
    aerospace_enabled: bool = False  # is AeroSpace on this Mac? then opening an app also goes to its workspace
    aerospace_command: str = "aerospace"
    aerospace_config: Path = Path("~/.config/aerospace/aerospace.toml").expanduser()
    aerospace_workspaces: tuple = ()  # (("Visual Studio Code", "C"), ...)
    screenshot_dir: str = "auto"
    screenshot_clipboard: bool = False
    screenshot_delay: int = 1
    ollama_command: str = "ollama"
    ollama_host: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3.8:27b"
    ollama_vision_model: str = ""  # describe_image: "" = the same model
    ollama_readme: str = "README.md"  # image tools: the file in the scanned folder where the descriptions are kept
    ollama_cache: str = "~/Library/Caches/mylauncher/image-captions.json"  # find_image: what the model saw in each picture
    ollama_think: object = None  # True / False / None (None = do not send the option)
    ollama_keep_alive: str = ""  # e.g. "10m": how long the model stays in memory
    ollama_timeout: int = 600
    ollama_autostart: bool = True
    ollama_prompts: Path = Path("prompts.json")  # relative paths: next to myconfiguration.json
    timer_folder: str = "~/.config/mylauncher/timers"  # one small file per running timer (the window counts down from them)
    images_folder: str = ""  # copy_image_topic: where to look when you type only the topic
    images_destination: str = ""  # copy_image_topic: where to copy to when you type only the topic
    briefing: dict = field(default_factory=lambda: dict(BRIEFING_DEFAULTS))
    timer_sound: str = "/System/Library/Sounds/Hero.aiff"
    timer_repeat: int = 4
    timer_volume: float = 3.0
    timer_speak: str = "Time is up"
    timer_system_volume: int = 0
    timer_big_clock: bool = True
    timer_confetti: bool = True
    timer_big_clock_seconds: int = 30
    gospel_feed_url: str = "https://rss.evangelizo.org/rss/v2/evangelizo_rss-am.xml"
    gospel_timeout: int = 20
    gospel_image_count: int = 3
    gospel_image_folder: str = "~/Pictures/daily-gospel"
    gospel_opening_prayers: Path = Path("opening_prayers.md")
    gospel_closing_prayers: Path = Path("closing_prayers.md")
    gospel_image_format: str = "jpg"
    gospel_image_quality: int = 95
    post_author: str = "Máximo Núñez Alarcón"
    post_language: str = "en"
    post_weight: int = 1
    post_categories: tuple = ("spirituality", "prayer")
    post_draft: bool = False
    post_featured_number: int = 1
    post_image_prefix: str = "/prayer/images"
    post_remote_host: str = "myserver"
    post_remote_images_dir: str = "/mnt/data/justtothepoint/static/prayer/images/"
    post_remote_post_dir: str = "/mnt/data/justtothepoint/prayer/"
    post_ssh_timeout: int = 15
    gospel_sources: tuple = ()  # ((title, url), ...) shown in the last line of the prayer; empty = the built-in three
    create_image_backend: str = "mflux"
    create_image_mflux_command: str = "~/macOS/myPython/.venv/bin/mflux-generate-flux2"
    create_image_mflux_args: tuple = ("--model", "flux2-klein-base-9b", "--quantize", "8", "--low-ram", "--steps", "50", "--guidance", "3.5", "--width", "1920", "--height", "1088")
    create_image_crop_size: str = "1920x1080"
    create_image_ollama_model: str = "x/z-image-turbo"
    create_image_openrouter_model: str = "bytedance-seed/seedream-4.5"
    create_image_folder: str = "~/Pictures/mylauncher"
    create_image_timeout: int = 180
    create_image_open_after: bool = True
    create_image_keychain_service: str = "justtothepoint-toolkit"
    create_image_keychain_user: str = "OPENROUTER_API_KEY"
    news_feeds_file: Path = Path("feeds.json")
    news_default: str = "news"
    news_cache_minutes: int = 15
    news_days: int = 7
    news_timeout: int = 8
    news_cache_folder: str = "~/Library/Caches/mylauncher"
    weather_location: str = ""
    weather_format: str = "%c+%t"
    weather_timeout: int = 6
    power_force: bool = True
    power_grace: int = 8
    power_lock: Path | None = Path("~/Library/Application Support/mylauncher/power.lock").expanduser()
    notify_method: str = "auto"  # auto, osascript, terminal-notifier, none
    toast: bool = False  # OFF by default (step 9f): an extra Cocoa window; the macOS notification is the reliable message. The launcher's own little message after an action (works without any macOS permission)
    toast_seconds: float = 2.0
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
    reserved = (config.kill_word, config.run_word, config.help_word, config.edit_word, config.execute_word, config.secret_word, config.secret_edit_word)
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

    # ---- aerospace and screenshot (optional) ---------------------------------
    aero = _check(data.get("aerospace", {}), dict, "aerospace")
    aero_enabled = _check(aero.get("enabled", False), bool, "aerospace.enabled")
    aero_command = _check(aero.get("command", "aerospace"), str, "aerospace.command").strip() or "aerospace"
    aero_config = Path(_check(aero.get("config", ""), str, "aerospace.config").strip() or _check(data.get("help", {}), dict, "help").get("aerospace_config", "~/.config/aerospace/aerospace.toml")).expanduser()
    raw_workspaces = _check(aero.get("workspaces", {}), dict, "aerospace.workspaces")
    aero_workspaces = tuple((str(app), _check(ws, str, f"aerospace.workspaces.{app}").strip()) for app, ws in raw_workspaces.items())
    power = _check(data.get("power", {}), dict, "power")
    power_force = _check(power.get("force", True), bool, "power.force")
    power_grace = _check(power.get("grace_seconds", 8), int, "power.grace_seconds")
    if not 0 <= power_grace <= 60:
        raise ConfigError("power.grace_seconds must be between 0 and 60")
    lock_text = _check(power.get("lock_file", "~/Library/Application Support/mylauncher/power.lock"), str, "power.lock_file")
    power_lock = Path(lock_text).expanduser() if lock_text.strip() else None
    ollama_section = _check(data.get("ollama", {}), dict, "ollama")
    ollama_model = _check(ollama_section.get("model", "qwen3.8:27b"), str, "ollama.model").strip()
    if not ollama_model:
        raise ConfigError('ollama.model must be a model name, for example "qwen3.8:27b"')
    ollama_vision = _check(ollama_section.get("vision_model", ""), str, "ollama.vision_model").strip()
    ollama_host = _check(ollama_section.get("host", "http://127.0.0.1:11434"), str, "ollama.host").strip()
    if not ollama_host.startswith(("http://", "https://")):
        raise ConfigError('ollama.host must start with http://, for example "http://127.0.0.1:11434"')
    ollama_think = ollama_section.get("think", False)
    if ollama_think is not None and not isinstance(ollama_think, bool):
        raise ConfigError("ollama.think must be true, false or null")
    ollama_timeout = _check(ollama_section.get("timeout_seconds", 600), int, "ollama.timeout_seconds")
    if ollama_timeout < 5:
        raise ConfigError("ollama.timeout_seconds must be at least 5")
    ollama_prompts = Path(_check(ollama_section.get("prompts_file", "prompts.json"), str, "ollama.prompts_file")).expanduser()
    if not ollama_prompts.is_absolute():
        ollama_prompts = Path(path).parent / ollama_prompts
    ollama_readme = _check(ollama_section.get("readme_file", "README.md"), str, "ollama.readme_file").strip() or "README.md"
    if "/" in ollama_readme:
        raise ConfigError("ollama.readme_file is a file NAME (README.md), not a path: it lives in the folder that is scanned")
    ollama_cache = _check(ollama_section.get("cache_file", "~/Library/Caches/mylauncher/image-captions.json"), str, "ollama.cache_file").strip()
    timer_section = _check(data.get("timer", {}), dict, "timer")
    timer_folder = _check(timer_section.get("folder", "~/.config/mylauncher/timers"), str, "timer.folder").strip() or "~/.config/mylauncher/timers"
    images_section = _check(data.get("images", {}), dict, "images")
    images_folder = _check(images_section.get("folder", ""), str, "images.folder").strip()
    images_destination = _check(images_section.get("destination", ""), str, "images.destination").strip()
    briefing_section = _check(data.get("briefing", {}), dict, "briefing")
    briefing = dict(BRIEFING_DEFAULTS)
    for b_name, b_default in BRIEFING_DEFAULTS.items():  # (b_ names: `key` is the hotkey's, used further down)
        briefing[b_name] = _check(briefing_section.get(b_name, b_default), type(b_default), f"briefing.{b_name}")
    if not 0 <= briefing["calendar_days"] <= 60 or not 0 <= briefing["mail_limit"] <= 100:
        raise ConfigError("briefing.calendar_days must be 0-60 and briefing.mail_limit 0-100 (0 = leave that source out)")
    timer_sound = _check(timer_section.get("sound", "/System/Library/Sounds/Hero.aiff"), str, "timer.sound").strip()
    timer_repeat = _check(timer_section.get("repeat", 4), int, "timer.repeat")
    if not 0 <= timer_repeat <= 20:
        raise ConfigError("timer.repeat must be between 0 and 20")
    timer_volume = timer_section.get("volume", 3.0)
    if isinstance(timer_volume, bool) or not isinstance(timer_volume, (int, float)) or not 0 < timer_volume <= 20:
        raise ConfigError("timer.volume must be a number above 0 and up to 20 (1 = as recorded)")
    timer_speak = _check(timer_section.get("speak", "Time is up"), str, "timer.speak")
    timer_system_volume = _check(timer_section.get("system_volume", 0), int, "timer.system_volume")
    if not 0 <= timer_system_volume <= 100:
        raise ConfigError("timer.system_volume must be 0 (do not touch) to 100")
    timer_big_clock = _check(timer_section.get("big_clock", True), bool, "timer.big_clock")
    timer_confetti = _check(timer_section.get("confetti", True), bool, "timer.confetti")
    timer_big_clock_seconds = _check(timer_section.get("big_clock_seconds", 30), int, "timer.big_clock_seconds")
    if timer_big_clock_seconds < 1:
        raise ConfigError("timer.big_clock_seconds must be 1 or more (the big clock appears when this many seconds are left)")
    ci = _check(data.get("create_image", {}), dict, "create_image")
    ci_backend = _check(ci.get("backend", "mflux"), str, "create_image.backend").strip().lower()
    if ci_backend not in ("mflux", "ollama", "openrouter"):
        raise ConfigError("create_image.backend must be \"mflux\" (local, free), \"ollama\" or \"openrouter\" (paid)")
    _crop = _check(ci.get("crop_size", "1920x1080"), str, "create_image.crop_size").strip().lower()
    if _crop and not re.fullmatch(r"\d{2,5}x\d{2,5}", _crop):
        raise ConfigError("create_image.crop_size is WIDTHxHEIGHT, for example 1920x1080 (empty = no cut)")
    ci_args = ci.get("mflux_args", ["--model", "flux2-klein-base-9b", "--quantize", "8", "--low-ram", "--steps", "50", "--guidance", "3.5", "--width", "1920", "--height", "1088"])
    if not isinstance(ci_args, list) or not all(isinstance(a, (str, int, float)) and not isinstance(a, bool) for a in ci_args):
        raise ConfigError("create_image.mflux_args must be a list of words, e.g. [\"--steps\", \"9\"]")
    ci_timeout = _check(ci.get("timeout_seconds", 180), int, "create_image.timeout_seconds")
    if ci_timeout < 5:
        raise ConfigError("create_image.timeout_seconds must be 5 or more")
    gs = _check(data.get("gospel", {}), dict, "gospel")
    gospel_url = _check(gs.get("feed_url", "https://rss.evangelizo.org/rss/v2/evangelizo_rss-am.xml"), str, "gospel.feed_url").strip()
    if not gospel_url.startswith(("http://", "https://")):
        raise ConfigError("gospel.feed_url must be an http(s) address")
    gospel_timeout = _check(gs.get("timeout_seconds", 20), int, "gospel.timeout_seconds")
    gospel_count = _check(gs.get("image_count", 3), int, "gospel.image_count")
    if gospel_timeout < 1 or not 1 <= gospel_count <= 12:
        raise ConfigError("gospel: timeout_seconds >= 1 and image_count between 1 and 12")
    def _beside(value, label):  # a file next to the configuration unless it is an absolute path
        file = Path(_check(value, str, label)).expanduser()
        return file if file.is_absolute() else Path(path).parent / file
    gospel_image_format = _check(gs.get("image_format", "jpg"), str, "gospel.image_format").strip().lower().lstrip(".")
    gospel_image_quality = _check(gs.get("image_quality", 95), int, "gospel.image_quality")
    gospel_sources_raw = gs.get("sources", [])
    if not isinstance(gospel_sources_raw, list) or not all(isinstance(x, dict) and isinstance(x.get("title"), str) and str(x.get("url", "")).startswith(("http://", "https://")) for x in gospel_sources_raw):
        raise ConfigError('gospel.sources must be a list like [{"title": "Pray As You Go", "url": "https://prayasyougo.org/"}]')
    ps = _check(data.get("post", {}), dict, "post")
    post_categories = ps.get("categories", ["spirituality", "prayer"])
    if not isinstance(post_categories, list) or not all(isinstance(c, str) and c.strip() for c in post_categories):
        raise ConfigError('post.categories must be a list of words, like ["spirituality", "prayer"]')
    post_weight = _check(ps.get("weight", 1), int, "post.weight")
    post_featured = _check(ps.get("featured_image_number", 1), int, "post.featured_image_number")
    post_timeout = _check(ps.get("ssh_timeout_seconds", 15), int, "post.ssh_timeout_seconds")
    post_prefix = _check(ps.get("image_url_prefix", "/prayer/images"), str, "post.image_url_prefix").strip()
    post_host = _check(ps.get("remote_host", "myserver"), str, "post.remote_host").strip()
    if post_featured < 1 or post_timeout < 1:
        raise ConfigError("post.featured_image_number and post.ssh_timeout_seconds must be 1 or more")
    if not post_host or post_host.startswith("-") or any(ch.isspace() for ch in post_host):
        raise ConfigError("post.remote_host is the Host alias of ~/.ssh/config (no spaces, not starting with -)")
    if not post_prefix.startswith("/"):
        raise ConfigError("post.image_url_prefix is the address of the pictures on the site, starting with /  (for example /prayer/images)")
    post_dirs = [_check(ps.get(k, d), str, f"post.{k}").strip() for k, d in (("remote_images_dir", "/mnt/data/justtothepoint/static/prayer/images/"), ("remote_post_dir", "/mnt/data/justtothepoint/prayer/"))]
    if not all(d.startswith("/") and len(d.strip("/")) > 3 for d in post_dirs):
        raise ConfigError("post.remote_images_dir and post.remote_post_dir are absolute folders on the server (like /mnt/data/justtothepoint/prayer/)")
    if gospel_image_format not in ("jpg", "jpeg", "png") or not 1 <= gospel_image_quality <= 100:
        raise ConfigError("gospel.image_format is jpg or png and image_quality 1-100")
    news_section = _check(data.get("news", {}), dict, "news")
    news_feeds = Path(_check(news_section.get("feeds_file", "feeds.json"), str, "news.feeds_file")).expanduser()
    if not news_feeds.is_absolute():
        news_feeds = Path(path).parent / news_feeds
    news_cache_minutes = _check(news_section.get("cache_minutes", 15), int, "news.cache_minutes")
    news_days = _check(news_section.get("days", 7), int, "news.days")
    news_timeout = _check(news_section.get("timeout_seconds", 8), int, "news.timeout_seconds")
    if news_cache_minutes < 0 or news_days < 1 or not 1 <= news_timeout <= 12:
        raise ConfigError("news: cache_minutes >= 0, days >= 1, timeout_seconds between 1 and 12 (a refresh from the window must end in 15 s)")
    weather_section = _check(data.get("weather", {}), dict, "weather")
    weather_location = _check(weather_section.get("location", ""), str, "weather.location").strip()
    weather_format = _check(weather_section.get("format", "%c+%t"), str, "weather.format").strip() or "%c+%t"
    weather_timeout = _check(weather_section.get("timeout_seconds", 6), int, "weather.timeout_seconds")
    if not 1 <= weather_timeout <= 30:
        raise ConfigError("weather.timeout_seconds must be between 1 and 30")
    shot = _check(data.get("screenshot", {}), dict, "screenshot")
    shot_dir = _check(shot.get("directory", "auto"), str, "screenshot.directory").strip() or "auto"
    shot_clip = _check(shot.get("clipboard", False), bool, "screenshot.clipboard")
    shot_delay = _check(shot.get("delay_seconds", 1), int, "screenshot.delay_seconds")
    if not 0 <= shot_delay <= 30:
        raise ConfigError("screenshot.delay_seconds must be between 0 and 30")

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
    paste = _check(expander.get("paste", True), bool, "expander.paste")
    paste_delay = _check(expander.get("paste_delay_ms", 250), int, "expander.paste_delay_ms")
    if paste_delay < 0:
        raise ConfigError("expander.paste_delay_ms cannot be negative")
    copy_log_text = _check(expander.get("copy_log", "~/Library/Logs/mylauncher/copy.log"), str, "expander.copy_log")
    copy_log = Path(copy_log_text).expanduser() if copy_log_text.strip() else None

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

    secret_section = data.get("secret", {})
    _check(secret_section, dict, "secret")
    secret_word = _check(secret_section.get("word", "secret"), str, "secret.word").lower()
    secret_edit_word = _check(secret_section.get("edit_word", "keep_secret"), str, "secret.edit_word").lower()
    secret_file = Path(_check(secret_section.get("file", "~/.config/mylauncher/secrets.env"), str, "secret.file")).expanduser()
    clear_seconds = _check(secret_section.get("clear_seconds", 30), int, "secret.clear_seconds")
    secret_service = _check(secret_section.get("keychain_service", "justtothepoint-toolkit"), str, "secret.keychain_service")
    reveal = _check(secret_section.get("reveal_chars", 4), int, "secret.reveal_chars")
    input_echo = _check(secret_section.get("input_echo", "hidden"), str, "secret.input_echo").lower()
    if input_echo not in ("hidden", "asterisks", "visible"):
        raise ConfigError('secret.input_echo must be "hidden", "asterisks" or "visible"')
    notify_value = _check(secret_section.get("notify_value", True), bool, "secret.notify_value")
    if clear_seconds < 0 or reveal < 0:
        raise ConfigError("secret.clear_seconds and secret.reveal_chars cannot be negative (0 = off)")

    notifications = data.get("notifications", {})
    _check(notifications, dict, "notifications")
    notify_method = _check(notifications.get("method", "auto"), str, "notifications.method")
    if notify_method not in NOTIFY_METHODS:
        raise ConfigError(f'notifications.method must be one of: {", ".join(NOTIFY_METHODS)}')
    toast = _check(notifications.get("toast", False), bool, "notifications.toast")
    toast_seconds = notifications.get("toast_seconds", 2.0)
    if isinstance(toast_seconds, bool) or not isinstance(toast_seconds, (int, float)) or toast_seconds <= 0:
        raise ConfigError("notifications.toast_seconds must be a number of seconds above 0")

    words = [run_word, kill_word, help_word, edit_word, execute_word, secret_word, secret_edit_word]
    for word_name, word in (("edit.word", edit_word), ("execute.word", execute_word), ("secret.word", secret_word), ("secret.edit_word", secret_edit_word)):
        if not word or len(word.split()) != 1:
            raise ConfigError(f"{word_name} must be ONE word")
    if len(set(words)) != len(words):
        raise ConfigError("apps.word, kill.word, help.word, edit.word, execute.word, secret.word and secret.edit_word must all be different words")
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
        aerospace_enabled=aero_enabled,
        aerospace_command=aero_command,
        aerospace_config=aero_config,
        aerospace_workspaces=aero_workspaces,
        power_force=power_force,
        power_grace=power_grace,
        power_lock=power_lock,
        screenshot_dir=shot_dir,
        screenshot_clipboard=shot_clip,
        screenshot_delay=shot_delay,
        ollama_command=_check(ollama_section.get("command", "ollama"), str, "ollama.command").strip() or "ollama",
        ollama_host=ollama_host,
        ollama_model=ollama_model,
        ollama_vision_model=ollama_vision,
        ollama_think=ollama_think,
        ollama_readme=ollama_readme,
        ollama_cache=ollama_cache,
        ollama_keep_alive=_check(ollama_section.get("keep_alive", ""), str, "ollama.keep_alive").strip(),
        ollama_timeout=ollama_timeout,
        ollama_autostart=_check(ollama_section.get("autostart", True), bool, "ollama.autostart"),
        ollama_prompts=ollama_prompts,
        timer_folder=timer_folder,
        images_folder=images_folder,
        images_destination=images_destination,
        briefing=briefing,
        timer_sound=timer_sound,
        timer_repeat=timer_repeat,
        timer_volume=float(timer_volume),
        timer_speak=timer_speak,
        timer_system_volume=timer_system_volume,
        timer_big_clock=timer_big_clock,
        timer_confetti=timer_confetti,
        timer_big_clock_seconds=timer_big_clock_seconds,
        gospel_feed_url=gospel_url,
        gospel_timeout=gospel_timeout,
        gospel_opening_prayers=_beside(gs.get("opening_prayers_file", "opening_prayers.md"), "gospel.opening_prayers_file"),
        gospel_closing_prayers=_beside(gs.get("closing_prayers_file", "closing_prayers.md"), "gospel.closing_prayers_file"),
        gospel_image_format="jpg" if gospel_image_format == "jpeg" else gospel_image_format,
        gospel_image_quality=gospel_image_quality,
        post_author=_check(ps.get("author", "Máximo Núñez Alarcón"), str, "post.author"),
        post_language=_check(ps.get("language", "en"), str, "post.language"),
        post_weight=post_weight,
        post_categories=tuple(post_categories),
        post_draft=_check(ps.get("draft", False), bool, "post.draft"),
        post_featured_number=post_featured,
        post_image_prefix=post_prefix,
        post_remote_host=post_host,
        post_remote_images_dir=post_dirs[0],
        post_remote_post_dir=post_dirs[1],
        post_ssh_timeout=post_timeout,
        gospel_sources=tuple((x["title"], x["url"]) for x in gospel_sources_raw),
        gospel_image_count=gospel_count,
        gospel_image_folder=_check(gs.get("image_folder", "~/Pictures/daily-gospel"), str, "gospel.image_folder").strip() or "~/Pictures/daily-gospel",
        create_image_backend=ci_backend,
        create_image_mflux_command=_check(ci.get("mflux_command", "~/macOS/myPython/.venv/bin/mflux-generate-flux2"), str, "create_image.mflux_command").strip(),
        create_image_mflux_args=tuple(str(a) for a in ci_args),
        create_image_crop_size=_crop,
        create_image_ollama_model=_check(ci.get("ollama_model", "x/z-image-turbo"), str, "create_image.ollama_model").strip(),
        create_image_openrouter_model=_check(ci.get("openrouter_model", "bytedance-seed/seedream-4.5"), str, "create_image.openrouter_model").strip(),
        create_image_folder=_check(ci.get("folder", "~/Pictures/mylauncher"), str, "create_image.folder").strip() or "~/Pictures/mylauncher",
        create_image_timeout=ci_timeout,
        create_image_open_after=_check(ci.get("open_after", True), bool, "create_image.open_after"),
        create_image_keychain_service=_check(ci.get("keychain_service", "justtothepoint-toolkit"), str, "create_image.keychain_service"),
        create_image_keychain_user=_check(ci.get("keychain_user", "OPENROUTER_API_KEY"), str, "create_image.keychain_user"),
        news_feeds_file=news_feeds,
        news_default=_check(news_section.get("default_category", "latest"), str, "news.default_category").strip() or "news",
        news_cache_minutes=news_cache_minutes,
        news_days=news_days,
        news_timeout=news_timeout,
        news_cache_folder=_check(news_section.get("cache_folder", "~/Library/Caches/mylauncher"), str, "news.cache_folder"),
        weather_location=weather_location,
        weather_format=weather_format,
        weather_timeout=weather_timeout,
        expander_notify=notify,
        expander_paste=paste,
        expander_paste_delay_ms=paste_delay,
        expander_copy_log=copy_log,
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
        secret_word=secret_word,
        secret_edit_word=secret_edit_word,
        secret_file=secret_file,
        secret_clear_seconds=clear_seconds,
        secret_reveal=reveal,
        secret_input_echo=input_echo,
        secret_notify_value=notify_value,
        secret_service=secret_service,
        notify_method=notify_method,
        toast=toast,
        toast_seconds=float(toast_seconds),
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
