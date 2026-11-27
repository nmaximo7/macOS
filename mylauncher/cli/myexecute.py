"""
myexecute.py - commands you can run from the launcher: conf/execute.json.

    [
      {"description": "help, my help script", "emoji": "📚", "command": "sh ~/macOS/scripts/help.sh -all", "terminal": true},
      {"description": "shutdown my computer", "emoji": "🔌", "command": "shutdown mac --now", "confirm": true}
    ]

  description  free text; the words before the first comma are the NAME you search for (like in edit.json).
  name         optional: the name, explicitly.
  emoji        optional (default ▶️).
  command      what to run. It is run by zsh, so `~`, `;`, `&&` and your FUNCTIONS work. Aliases do NOT
               (they only exist in an interactive shell): write the real command instead.
  terminal     optional, true/false (default: `execute.terminal` of the configuration, false).
               true: open a terminal window and run it there, so you SEE the output and can answer
               questions. false: run it in the background; a notification tells you when it finished
               (and the output goes to a log file).
  confirm      optional, true: the launcher asks "are you sure?" first (use it for shutdown).

How you use it:   execute   (then Space)   help   (then Enter)

How the command is run (everything can be changed in the `execute` section of myconfiguration.json):
    /bin/zsh -lc "[ -f ~/.zsh_functions ] && . ~/.zsh_functions; ( YOUR COMMAND ) ..."
 -l  a login shell, so Homebrew and your PATH are there;  the files in `execute.source` (default
 ~/.zsh_functions) are loaded first, so your zsh functions exist. No -i: no aliases, no slow prompt setup.

GUIDED TOUR: (1) ExecEntry + parse_execute/load_execute: the same shape as myedit.py (it even re-uses parse_text_field);
(2) the SCRIPTS: three functions that build the text of a small shell script; (3) build_execute_items: entries -> rows.

WHY BUILD A SCRIPT AS TEXT? We hand zsh one string to run. Writing it as a list of lines makes each rule visible:
    ( [ -f ~/.zsh_functions ] && . ~/.zsh_functions; YOUR COMMAND
    )
    code=$?                                         <- remember how it ended (0 = success)
    if [ "$code" -eq 0 ]; then msg="finished"; ...  <- background: notify success or failure
    exit "$code"                                    <- the launcher learns the real exit code
Three details worth understanding:
  * The command runs inside ( ... ), a SUB-SHELL: if your command contains `exit 3`, only the sub-shell exits, so the lines AFTER it (the
    notification) still run.
  * The backslash-n (newline) before `)` is deliberate: if your command ends with a `# comment`, a `)` on the same line would be swallowed by the comment.
  * `[ -f FILE ] && . FILE;` = "if the file exists, load it" (`.` is `source`). A missing file is not an error.
Two modes: background (output to a log, notification at the end) or terminal (a window that waits for Enter so you can read the output).
`plain()` and `shlex.quote()` are the two protections: quote anything that becomes part of a shell line, never trust a name.
"""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path

from dataclasses import dataclass

from mytypes import ConfigError, Item
from myedit import parse_text_field
from mynotify import script_line

# {command} is replaced by the whole script. Ghostty is started with `open -na` (a macOS app is not
# started by running its program directly); -e = "run this program instead of your shell".
# A tuple of words, with the placeholder "{command}" replaced by the whole script at run time (see myactions.execute_terminal).
DEFAULT_TERMINAL_COMMAND = ("open", "-na", "Ghostty", "--args", "-e", "/bin/zsh", "-lc", "{command}")
DEFAULT_SHELL = ("/bin/zsh", "-lc")
DEFAULT_SOURCE = ("~/.zsh_functions",)


@dataclass(frozen=True)
class ExecEntry:
    name: str
    description: str
    emoji: str
    command: str
    # `bool | None` = three states: True, False, or None ("not said: use the global setting"). Three states cannot be a plain bool.
    terminal: bool | None = None  # None = use the default of the configuration
    confirm: bool = False


def parse_execute(data, where: str = "execute.json") -> tuple:
    if not isinstance(data, list):
        raise ConfigError(f"{where} must be a list [ {{...}}, {{...}} ]")
    entries = []
    for number, entry in enumerate(data):
        here = f"{where}[{number}]"
        if not isinstance(entry, dict):
            raise ConfigError(f"{here} must be an object with a description and a command")
        name, description, emoji = parse_text_field(entry, here)
        command = entry.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ConfigError(f'{here}.command must be text, for example "sh ~/macOS/scripts/help.sh -all"')
        terminal = entry.get("terminal")
        if terminal is not None and not isinstance(terminal, bool):
            raise ConfigError(f"{here}.terminal must be true or false")
        confirm = entry.get("confirm", False)
        if not isinstance(confirm, bool):
            raise ConfigError(f"{here}.confirm must be true or false")
        entries.append(ExecEntry(name, description, emoji, command.strip(), terminal, confirm))
    return tuple(entries)


def load_execute(path) -> tuple:
    """Read conf/execute.json. A missing file means "no commands" (it is optional)."""
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
    return parse_execute(data, path.name)


# --------------------------------------------------------------------------- #
# The shell scripts we hand to zsh
# --------------------------------------------------------------------------- #
def source_prefix(source_files) -> str:
    """`[ -f FILE ] && . FILE;` for each file: load your functions, and do not complain if a file is missing."""
    parts = []
    for name in source_files:
        quoted = shlex.quote(str(Path(name).expanduser()))
        parts.append(f"[ -f {quoted} ] && . {quoted}; ")
    return "".join(parts)


# `re.sub(r'["\\$`\n]', "", text)` deletes every double quote, backslash, dollar sign, backtick and newline: the characters that could
# break out of a shell or AppleScript string. A name is only DISPLAYED, so removing them costs nothing and removes a whole attack class.
def plain(text: str) -> str:
    """A name safe inside shell and AppleScript double quotes: quotes, backslashes, $ and ` are removed."""
    return re.sub(r'["\\$`\n]', "", text)


def background_script(name: str, command: str, source_files, notify: bool = True, method: str = "auto") -> str:
    """Run the command in a sub-shell (an `exit` inside it cannot skip what follows), then say how it went."""
    lines = [f"( {source_prefix(source_files)}{command}\n)", "code=$?"]
    if notify:
        lines += [
            'if [ "$code" -eq 0 ]; then msg="finished"; else msg="failed (exit $code), see the log"; fi',
            script_line(method, name),
        ]
    lines.append('exit "$code"')
    return "\n".join(lines)


def terminal_script(command: str, source_files) -> str:
    """Same, but in a terminal window: show the exit code and wait, so the window does not vanish with the output."""
    return "\n".join(
        [
            f"( {source_prefix(source_files)}{command}\n)",
            "code=$?",
            'echo; echo "[mylauncher] finished with exit code $code. Press Enter to close."',
            "read",
            'exit "$code"',
        ]
    )


def build_execute_items(config) -> list:
    items = []
    for entry in config.execute_entries:
        terminal = config.execute_terminal if entry.terminal is None else entry.terminal
        subtitle = f"{entry.description}  ·  {entry.command}" if entry.description else entry.command
        items.append(
            Item(
                id=f"execute:{entry.name}",
                title=entry.name,
                kind="execute",
                action="execute_terminal" if terminal else "execute_background",
                target=entry.command,
                complete=f"{config.execute_word} {entry.name}",  # what Tab writes
                confirm=entry.confirm,
                keywords=tuple(k for k in (entry.description, entry.command) if k),
                subtitle=subtitle,
                icon=entry.emoji,
                badge="Terminal" if terminal else "Background",
            )
        )
    return items
