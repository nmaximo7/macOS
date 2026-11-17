"""
myhelp.py - "help": a memory aid for your own Mac, inside the launcher.

You forget which aliases you created, what a function of ~/.zsh_functions does, which AeroSpace key
moves a window, what a script in ~/macOS/scripts is for. Instead of grepping, you type:

    help                     the topics
    help aliases             every alias (and its command)
    help functions deploy    the functions whose name or comment contains "deploy"
    help aerospace           the key bindings of ~/.config/aerospace/aerospace.toml
    ... espanso, skills, keys (help.sh), scripts, system, launcher

The same information is available in the terminal:  ml help aliases  /  ml help functions --json.

Where each topic reads from (everything is READ-ONLY: nothing is written, nothing of yours is run,
except `zsh -ic alias` and a few `--version` commands):
    aliases    `zsh -ic alias` (the aliases that really are active), plus the comments written above each
               alias in help.aliases_file
    functions  the file help.functions_file (parsed here, no shell needed): name, comment above, source
    aerospace  help.aerospace_config (TOML): [mode.*.binding] and [[on-window-detected]]
    espanso    the same snippet files the launcher already reads (expander.folder)
    skills     SKILL.md files under help.skills_folder (name and description from the front matter)
    keys       the `sec_<name>() { ... }` functions of help.script (your own cheat sheets)
    scripts    the files of help.scripts_folder: name, first comment line, first lines
    system     macOS, chip, memory, disk, zsh, AeroSpace, Python
    launcher   the words and keys of mylauncher itself, from conf/myconfiguration.json

Every answer is a list of ROWS: title, a one-line subtitle and a longer `detail` (the window shows it
when you press Enter on a row; Enter again copies it). Asking a shell (aliases) is slow, so those
answers are remembered for help.cache_seconds in a small file outside the repository.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from mysearch import rank
from mytypes import Item, Match

try:
    import tomllib
except ModuleNotFoundError:  # Python older than 3.11: the aerospace topic says so
    tomllib = None

# name: (emoji, what it shows, label at the end of the row)
TOPICS = {
    "aliases": ("🔗", "Shell aliases (zsh -ic alias)", "Alias"),
    "functions": ("🧩", "Functions of your ~/.zsh_functions", "Function"),
    "aerospace": ("🪟", "AeroSpace key bindings and rules", "AeroSpace"),
    "espanso": ("✂️", "Espanso snippets and where they live", "Espanso"),
    "skills": ("🧠", "Claude skills (SKILL.md)", "Skill"),
    "keys": ("⌨️", "Your cheat sheets: sections of help.sh", "Cheat sheet"),
    "scripts": ("📜", "The scripts folder: what each script is for", "Script"),
    "system": ("🖥️", "This Mac: macOS, chip, memory, disk, versions", "System"),
    "launcher": ("🚀", "What mylauncher itself understands", "Launcher"),
    "screenshot": ("📸", "Screenshots: the macOS shortcuts and the launcher commands", "Screenshot"),
}
# Other names that mean the same topic (you wrote "help zsh_alias" and "help zsh_functions").
SYNONYMS = {
    "alias": "aliases", "zsh_alias": "aliases", "zsh_aliases": "aliases", "aliase": "aliases",
    "function": "functions", "func": "functions", "zsh_function": "functions", "zsh_functions": "functions",
    "aero": "aerospace", "wm": "aerospace",
    "snippets": "espanso", "snippet": "espanso", "text": "espanso",
    "skill": "skills", "screenshots": "screenshot", "screen": "screenshot", "capture": "screenshot", "shots": "screenshot",
    "key": "keys", "keyboard": "keys", "shortcuts": "keys", "cheatsheets": "keys", "sections": "keys",
    "script": "scripts",
    "sys": "system", "info": "system", "mac": "system",
    "app": "launcher", "mylauncher": "launcher",
}
CACHED = ("aliases", "system")  # the slow ones (they start programs)


@dataclass
class Row:
    uid: str  # unique inside its topic (a title can repeat: the same key in two AeroSpace modes)
    title: str
    subtitle: str = ""
    detail: str = ""
    target: str = ""  # what Enter copies to the clipboard (default: the detail)


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def resolve_topic(word: str) -> str:
    """"zsh_alias" -> "aliases"; "" if the word is not a topic."""
    w = word.lower().replace("-", "_")
    return w if w in TOPICS else SYNONYMS.get(w, "")


def comment_above(lines: list, index: int) -> str:
    """The block of `# comment` lines right above lines[index], as plain text (no # signs)."""
    found = []
    i = index - 1
    while i >= 0 and lines[i].lstrip().startswith("#") and not lines[i].startswith("#!"):
        found.append(lines[i].lstrip().lstrip("#").strip())
        i -= 1
    return "\n".join(reversed(found)).strip()


def read_text(path: Path) -> str | None:
    try:
        return Path(path).expanduser().read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def first_line(text: str) -> str:
    return next((ln.strip() for ln in text.splitlines() if ln.strip()), "")


# --------------------------------------------------------------------------- #
# aliases
# --------------------------------------------------------------------------- #
def parse_alias_output(text: str) -> dict:
    """The output of `alias`:   ll='ls -la'   or   gs=git\\ status   ->  {"ll": "ls -la", ...}."""
    aliases = {}
    for line in text.splitlines():
        name, sep, value = line.partition("=")
        if not sep or not name.strip() or " " in name.strip():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        aliases[name.strip()] = value.replace("'\\''", "'")  # zsh writes a ' inside quotes as '\''
    return aliases


ALIAS_DEFINITION = re.compile(r"^\s*alias\s+(?:-\w+\s+)?([^=\s]+)=")


def alias_rows(config, runner) -> tuple:
    try:
        done = runner(["zsh", "-ic", "alias"])
    except FileNotFoundError:
        return [], "zsh was not found"
    if done.returncode != 0 and not (done.stdout or "").strip():
        return [], f"`zsh -ic alias` failed: {(done.stderr or '').strip() or done.returncode}"
    comments = {}
    text = read_text(config.help_aliases_file)
    if text:
        lines = text.splitlines()
        for i, line in enumerate(lines):
            m = ALIAS_DEFINITION.match(line)
            if m:
                comments[m.group(1)] = comment_above(lines, i)
    rows = []
    for name, value in sorted(parse_alias_output(done.stdout or "").items()):
        note = comments.get(name, "")
        detail = f"alias {name}='{value}'" + (f"\n\n{note}" if note else "") + f"\n\nSee its definition in a terminal:  type {name}"
        rows.append(Row(name, name, value + (f"   # {first_line(note)}" if note else ""), detail, name))
    return rows, "no aliases found (is ~/.zshrc printing something that breaks `zsh -ic alias`?)" if not rows else ""


# --------------------------------------------------------------------------- #
# functions
# --------------------------------------------------------------------------- #
FUNCTION_START = re.compile(r"^(?:function\s+)?([A-Za-z0-9][\w.:+-]*)\s*(?:\(\s*\))?\s*\{\s*(?:#.*)?$")


def function_blocks(text: str) -> list:
    """[(name, comment, source)] for the functions defined at the left margin of a shell file.

    A function starts at `name() {` (or `function name {`) and ends where its braces balance. Counting
    braces is not a real parser (a brace inside a string fools it) but it is right for ordinary scripts.
    """
    lines = text.splitlines()
    found, i = [], 0
    while i < len(lines):
        m = FUNCTION_START.match(lines[i])
        if not m or m.group(1).startswith("_"):  # _private helpers are left out
            i += 1
            continue
        depth, j = 0, i
        while j < len(lines):
            depth += lines[j].count("{") - lines[j].count("}")
            if depth <= 0:
                break
            j += 1
        found.append((m.group(1), comment_above(lines, i), "\n".join(lines[i : j + 1])))
        i = j + 1
    return found


def function_rows(config, runner) -> tuple:
    text = read_text(config.help_functions_file)
    if text is None:
        return [], f"file not found: {config.help_functions_file} (help.functions_file)"
    rows = []
    for name, comment, source in function_blocks(text):
        summary = first_line(comment) or first_line("\n".join(source.splitlines()[1:]))
        detail = (comment + "\n\n" if comment else "") + source
        rows.append(Row(name, name, summary, detail, name))
    return sorted(rows, key=lambda r: r.title), "no functions found in the file" if not rows else ""


# --------------------------------------------------------------------------- #
# aerospace
# --------------------------------------------------------------------------- #
def aerospace_rows(config, runner) -> tuple:
    path = Path(config.help_aerospace_config).expanduser()
    if tomllib is None:
        return [], "needs Python 3.11 or newer (tomllib)"
    if not path.exists():
        return [], f"file not found: {path} (help.aerospace_config)"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return [], f"cannot read {path}: {exc}"
    rows = []
    for mode, body in data.get("mode", {}).items():
        for key, action in (body.get("binding", {}) or {}).items():
            action = " ; ".join(action) if isinstance(action, list) else str(action)
            rows.append(Row(f"{mode}:{key}", key, action, f"mode: {mode}\nkey: {key}\naction: {action}", f"{key}  ->  {action}"))
    for n, rule in enumerate(data.get("on-window-detected", []) or []):
        when = ", ".join(f"{k}={v}" for k, v in rule.items() if k.startswith("if"))
        run = rule.get("run", "")
        run = " ; ".join(run) if isinstance(run, list) else str(run)
        rows.append(Row(f"rule{n}", f"rule: {when or '(any window)'}", run, f"when a window is detected\n{when}\nrun: {run}", run))
    return rows, "no key bindings found in the file" if not rows else ""


# --------------------------------------------------------------------------- #
# espanso
# --------------------------------------------------------------------------- #
def espanso_rows(config, runner) -> tuple:
    from myexpander import load_snippets

    if not config.expander_enabled:
        return [], "expander.folder is not set in the configuration"
    scan = load_snippets(config.expander_folder, config.expander_strip_cursor)
    if scan.missing_yaml:
        return [], "PyYAML is not installed: .venv/bin/pip install pyyaml"
    rows = [
        Row(s.trigger, s.trigger, first_line(s.text), f"trigger: {s.trigger}\nfile: {s.source}\n\n{s.text}", s.text)
        for s in sorted(scan.snippets, key=lambda s: s.trigger)
    ]
    return rows, f"no snippets found in {config.expander_folder}" if not rows else ""


# --------------------------------------------------------------------------- #
# skills
# --------------------------------------------------------------------------- #
FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---(?:\s|\Z)", re.S)


def skill_info(text: str, fallback: str) -> tuple:
    """(name, description) from the front matter of a SKILL.md. Uses PyYAML if it is there, else a simple reading."""
    m = FRONT_MATTER.match(text)
    if not m:
        return fallback, ""
    from myexpander import yaml_loader

    loader = yaml_loader()
    if loader:
        try:
            meta = loader(m.group(1)) or {}
            return str(meta.get("name", fallback)), " ".join(str(meta.get("description", "")).split())
        except Exception:  # noqa: BLE001  (a broken front matter must not hide the other skills)
            pass
    name = re.search(r"^name:\s*(.+)$", m.group(1), re.M)
    description = re.search(r"^description:\s*(.+)$", m.group(1), re.M)
    return (name.group(1).strip() if name else fallback), (description.group(1).strip() if description else "")


def skill_rows(config, runner) -> tuple:
    root = Path(config.help_skills_folder).expanduser()
    if not root.is_dir():
        return [], f"folder not found: {root} (help.skills_folder)"
    rows = []
    for path in sorted(root.rglob("SKILL.md")):
        name, description = skill_info(path.read_text(encoding="utf-8", errors="replace"), path.parent.name)
        rows.append(Row(str(path), name, description, f"{name}\n\n{description}\n\n{path.parent}", name))
    return rows, f"no SKILL.md files under {root}" if not rows else ""


# --------------------------------------------------------------------------- #
# keys: the sec_<name>() cheat sheets of help.sh
# --------------------------------------------------------------------------- #
SECTION = re.compile(r"^sec_(?P<name>\w+)\s*\(\)\s*\{(?P<body>.*?)^\}", re.S | re.M)
ECHO_LINE = re.compile(r"""^\s*(?:echo|printf)(?:\s+-\w+)*\s+(['"])(?P<text>.*)\1\s*$""")
ANSI = re.compile(r"(\\033|\\e|\\x1b)\[[0-9;]*m|\x1b\[[0-9;]*m")


def clean_shell_text(body: str) -> str:
    """The text of a cheat sheet written with echo/printf: remove the commands, quotes and colour codes."""
    lines = []
    for line in body.strip("\n").splitlines():
        m = ECHO_LINE.match(line)
        lines.append(ANSI.sub("", m.group("text") if m else line.strip()))
    return "\n".join(lines).strip()


def keys_rows(config, runner) -> tuple:
    text = read_text(config.help_script)
    if text is None:
        return [], f"file not found: {config.help_script} (help.help_script)"
    rows = []
    for m in SECTION.finditer(text):
        body = clean_shell_text(m.group("body"))
        rows.append(Row(m.group("name"), m.group("name"), first_line(body), body, body))
    return rows, "no sec_<name>() functions found in the file" if not rows else ""


# --------------------------------------------------------------------------- #
# scripts
# --------------------------------------------------------------------------- #
def script_summary(text: str) -> str:
    """The first comment (or docstring) line after the shebang: what the author wrote to remember it."""
    for line in text.splitlines()[:30]:
        stripped = line.strip().lstrip("#").strip().strip('"').strip("'").strip()
        if not stripped or line.startswith("#!") or stripped.startswith(("-*-", "coding", "shellcheck", "set ", "from __future__")):
            continue
        if line.strip().startswith(("#", '"""', "'''", '"', "'")):
            return stripped
        break
    return ""


def script_rows(config, runner) -> tuple:
    root = Path(config.help_scripts_folder).expanduser()
    if not root.is_dir():
        return [], f"folder not found: {root} (help.scripts_folder)"
    rows = []
    for path in sorted(root.iterdir()):
        if path.name.startswith(".") or not path.is_file():
            continue
        text = read_text(path)
        if text is None or "\0" in text[:200]:  # unreadable or a binary file
            continue
        head = "\n".join(text.splitlines()[:40])
        rows.append(Row(path.name, path.name, script_summary(text), f"{path}\n\n{head}", str(path)))
    return rows, f"no files in {root}" if not rows else ""


# --------------------------------------------------------------------------- #
# system
# --------------------------------------------------------------------------- #
def _out(runner, command) -> str:
    try:
        done = runner(command)
    except FileNotFoundError:
        return "not installed"
    return ((done.stdout or "").strip() if done.returncode == 0 else "") or "unknown"


def system_rows(config, runner) -> tuple:
    memory = _out(runner, ["sysctl", "-n", "hw.memsize"])
    ram = f"{int(memory) / 1024**3:.1f} GB" if memory.isdigit() else memory
    free = shutil.disk_usage("/").free / 1024**3
    facts = [
        ("macOS", _out(runner, ["sw_vers", "-productVersion"])),
        ("Architecture", _out(runner, ["uname", "-m"])),
        ("Memory", ram),
        ("Disk free", f"{free:.1f} GB"),
        ("zsh", _out(runner, ["zsh", "--version"])),
        ("AeroSpace", _out(runner, ["aerospace", "--version"])),
        ("Python (launcher)", f"{sys.version.split()[0]}  {sys.executable}"),
    ]
    return [Row(n, n, v, f"{n}: {v}", v) for n, v in facts], ""


# --------------------------------------------------------------------------- #
# launcher: what mylauncher itself understands (built from the configuration)
# --------------------------------------------------------------------------- #
def launcher_rows(config, runner) -> tuple:
    rows = [
        Row("hotkey", "hotkey", "+".join(config.hotkey_modifiers) + "+" + config.hotkey_key, "Shows or hides the window.", ""),
        Row("run", config.run_word, "lists every application", f"{config.run_word}            all applications\n{config.run_word} saf        filter them", ""),
        Row("kill", config.kill_word, "close an application", f"{config.kill_word} <name>     quits it; asks before a force quit", ""),
        Row("help", config.help_word, "this help", f"{config.help_word}              the topics\n{config.help_word} aliases      a topic\n{config.help_word} functions x  a topic, filtered by x", ""),
        Row("edit", config.edit_word, "open a file in your editor", f"{config.edit_word} <name>   opens a file of edit.json in the editor ({' '.join(config.edit_editor)})", ""),
        Row("execute", config.execute_word, "run one of your commands", f"{config.execute_word} <name>   runs a command of execute.json (in a terminal or in the background)", ""),
        Row("secret", config.secret_word, "your secrets, values hidden", f"{config.secret_word} google   copies the value and shows it in the notification\n{config.secret_word} private_vault   the private_notes of every entry\n{config.secret_word}   the entries of the secret file; Enter shows one, Enter again copies it (the clipboard is emptied after {config.secret_clear_seconds} s)\n{config.secret_edit_word}   opens the file in the editor", ""),
        Row("screenshot", "screenshot", "full_screen or region", "screenshot full_screen   the whole screen\nscreenshot region        drag to choose an area\nhelp screenshot          the macOS shortcuts (⇧⌘3, ⇧⌘4, ⇧⌘5)", ""),
        Row("weather", "weather", "the weather now (wttr.in)", "weather   one line (icon and temperature) in a notification; place and format: the \"weather\" section of the configuration", ""),
        Row("reboot", "reboot", "restart the Mac (asks first)", "reboot   asks, then restarts the Mac", ""),
        Row("snippets", ";", "snippet groups, then snippets", "; lists the groups; ;p the snippets of the group ;p. Enter copies the text.", ""),
    ]
    for link in config.quicklinks:
        rows.append(Row(f"link:{link.keyword}", link.keyword, f"web search: {link.title}", f"{link.keyword} <text>   opens {link.url}", ""))
    for key, what in (("↓ ↑", "move"), ("Tab", "complete"), ("Enter", "do / open details"), ("Esc", "back / close")):
        rows.append(Row(f"key:{key}", key, what, what, ""))
    return rows, ""


# --------------------------------------------------------------------------- #
# screenshot (the shortcuts of macOS: a fixed list, because they are the SYSTEM's, not yours)
# --------------------------------------------------------------------------- #
SHORTCUTS = (
    ("⇧⌘3", "Whole screen, saved as a file", "Shift + Command + 3.\nHold Control as well (⌃⇧⌘3) to copy it to the clipboard instead of saving a file."),
    ("⇧⌘4", "A region (drag a rectangle)", "Shift + Command + 4, then drag the crosshair over the area.\nEsc cancels. While dragging: Space moves the area, Shift locks one side, Option resizes from the centre.\nControl as well (⌃⇧⌘4) copies to the clipboard."),
    ("⇧⌘4 then Space", "One window", "Shift + Command + 4, press Space (the cross becomes a camera), click the window.\nHold Option while clicking to leave out the window's shadow."),
    ("⇧⌘5", "The screenshot toolbar", "Shift + Command + 5 opens the toolbar: whole screen, window, region, screen recording, a timer, and Options (where to save, show the pointer...)."),
    ("Esc", "Cancel", "Escape cancels a capture you started."),
)


def screenshot_rows(config, runner) -> tuple:
    where = "the place macOS uses (Desktop unless you changed it)" if config.screenshot_dir == "auto" else config.screenshot_dir
    target = "the clipboard" if config.screenshot_clipboard else where
    rows = [
        Row("full", "screenshot full_screen", f"launcher: the whole screen after {config.screenshot_delay} s", f"Type  screenshot full_screen  and press Enter.\nThe window hides, {config.screenshot_delay} s later the whole screen is captured -> {target}.\nSame as ⇧⌘3.", ""),
        Row("region", "screenshot region", "launcher: drag to choose an area", f"Type  screenshot region  and press Enter.\nThe cross appears: drag over the area (Esc cancels) -> {target}.\nSame as ⇧⌘4.", ""),
    ]
    rows += [Row(f"key:{key}", key, what, f"{key}   {what}\n\n{text}", "") for key, what, text in SHORTCUTS]
    rows.append(Row("perm", "first time: permission", "System Settings > Privacy & Security > Screen Recording",
                    "The launcher takes the picture with the macOS program `screencapture`. The first time, macOS may ask to allow Screen Recording for python:\nSystem Settings > Privacy & Security > Screen & System Audio Recording > add the python path that setup.sh printed.\nThe keyboard shortcuts above need no permission.", ""))
    return rows, ""


LOADERS = {
    "aliases": alias_rows, "functions": function_rows, "aerospace": aerospace_rows, "espanso": espanso_rows,
    "skills": skill_rows, "keys": keys_rows, "scripts": script_rows, "system": system_rows, "launcher": launcher_rows, "screenshot": screenshot_rows,
}


# --------------------------------------------------------------------------- #
# the cache for the slow topics
# --------------------------------------------------------------------------- #
def _cache_load(config) -> dict:
    try:
        data = json.loads(Path(config.help_cache_file).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _cache_store(config, topic: str, rows: list) -> None:
    data = _cache_load(config)
    data[topic] = {"time": time.time(), "rows": [asdict(r) for r in rows]}
    path = Path(config.help_cache_file)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, path)  # atomic: a crash never leaves half a file
    except OSError:
        pass  # a cache that cannot be written only makes the next answer slower


def load_rows(config, topic: str, runner, refresh: bool = False) -> tuple:
    """(rows, problem) of a topic. `problem` is empty when all is well."""
    use_cache = topic in CACHED and config.help_cache_seconds > 0
    if use_cache and not refresh:
        entry = _cache_load(config).get(topic)
        if entry and time.time() - entry.get("time", 0) < config.help_cache_seconds:
            try:
                return [Row(**r) for r in entry["rows"]], ""
            except TypeError:
                pass
    rows, problem = LOADERS[topic](config, runner)
    if use_cache and rows:
        _cache_store(config, topic, rows)
    return rows, problem


# --------------------------------------------------------------------------- #
# rows -> launcher items, and the search
# --------------------------------------------------------------------------- #
def row_item(config, topic: str, row: Row) -> Item:
    icon, _, label = TOPICS[topic]
    return Item(
        id=f"help:{topic}:{row.uid}", title=row.title, kind="help", action="copy_snippet", target=row.target or row.detail,
        complete=f"{config.help_word} {topic} {row.title}",  # Tab keeps "help <topic>" and adds the row's name
        keywords=tuple(k for k in (row.subtitle[:120], " ".join(row.detail.split())[:400]) if k), subtitle=row.subtitle, icon=icon, badge=label, detail=row.detail,
    )


def topic_items(config) -> list:
    return [
        Item(id=f"helptopic:{name}", title=name, kind="prefix", action="prefix_hint", complete=f"{config.help_word} {name} ",
             subtitle=what, icon=icon, badge="Topic")
        for name, (icon, what, _label) in TOPICS.items()
    ]


def problem_item(config, topic: str, problem: str) -> Item:
    return Item(id=f"info:help:{topic}", title=f"Nothing to show for “{topic}”", kind="prefix", action="prefix_hint",
                complete=f"{config.help_word} ", subtitle=problem, icon="⚠️", badge="Fix")


def parse_help_query(config, query: str) -> tuple:
    """"help zsh_alias ll" -> ("aliases", "ll", end) ; "help al" -> ("", "al", end_of_word).

    `end` = how many characters at the start of the query are the recognised command (to colour them).
    """
    m = re.match(r"^(\s*\S+)(?:(\s+)(\S+))?(?:\s+(.*))?$", query)
    if not m:
        return "", "", 0
    word_end = len(m.group(1))
    second, rest = m.group(3) or "", (m.group(4) or "").strip()
    topic = resolve_topic(second) if second else ""
    if topic:
        return topic, rest, word_end + len(m.group(2)) + len(second)
    return "", " ".join(part for part in (second, rest) if part), word_end


def help_search(config, query: str, runner, refresh: bool = False, **options) -> list:
    topic, rest, _ = parse_help_query(config, query)
    limit = config.max_browse_results

    def choose(items):
        if not rest.strip():  # nothing to filter by: keep OUR order (topics as listed, bindings as in the file)
            return [Match(item, 100) for item in items[:limit]]
        # No "letters in order" matches: against a long text they would match almost anything.
        return rank(items, rest, limit, **{**options, "fuzzy": False})

    if not topic:  # "help" or "help al": the topics, filtered by what is typed
        return choose(topic_items(config))
    rows, problem = load_rows(config, topic, runner, refresh)
    if not rows:
        return [Match(problem_item(config, topic, problem), 100)]
    return choose([row_item(config, topic, r) for r in rows])


def help_end(config, query: str) -> int:
    """How many characters of the query to colour (see parse_help_query)."""
    return parse_help_query(config, query)[2]
