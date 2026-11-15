"""
mynotify.py - macOS notifications, in the one place that knows how.

Three ways to show a notification, chosen by `notifications.method` in conf/myconfiguration.json:

  osascript          `osascript -e 'display notification ...'`. Needs nothing installed, but the notification
                     is shown as coming from "Script Editor", and on recent macOS it is often silently dropped
                     (Focus modes, "Script Editor" never opened, a launch agent with no GUI link...).
                     osascript says "success" even when nothing is shown, so we cannot detect that.
  terminal-notifier  `brew install terminal-notifier`: a tiny app of its own. The first time it posts, macOS
                     adds "terminal-notifier" to System Settings > Notifications: allow it there. Much more
                     reliable than osascript.
  none               no macOS notification (the window still shows its own message, see mytoast.py)

  auto (default)     terminal-notifier if it is installed, otherwise osascript.

`ml notify-test` sends a test and tells what happened.
"""

from __future__ import annotations

import shlex
import shutil

from mykill import applescript_quote

METHODS = ("auto", "osascript", "terminal-notifier", "none")


def resolve(method: str, which=shutil.which) -> tuple:
    """(name, path-or-empty): the method that will really be used. "auto" looks for terminal-notifier."""
    if method in ("none",):
        return "none", ""
    if method in ("terminal-notifier", "auto"):
        found = which("terminal-notifier")
        if found:
            return "terminal-notifier", found
        if method == "terminal-notifier":
            return "terminal-notifier", "terminal-notifier"  # not found: the caller reports the failure
    return "osascript", "osascript"


def argv(method: str, title: str, subtitle: str, message: str, which=shutil.which) -> list:
    """The command that shows the notification ([] for "none")."""
    name, path = resolve(method, which)
    if name == "none":
        return []
    if name == "terminal-notifier":
        command = [path, "-title", title, "-message", message or " ", "-group", "mylauncher"]
        return command + (["-subtitle", subtitle] if subtitle else [])
    script = f'display notification "{applescript_quote(message)}" with title "{applescript_quote(title)}"'
    if subtitle:
        script += f' subtitle "{applescript_quote(subtitle)}"'
    return [path, "-e", script]


def send(runner, method: str, title: str, subtitle: str, message: str, which=shutil.which) -> tuple:
    """Show a notification. Returns (ok, detail): detail says why not when ok is False.

    ok only means "the helper program accepted it": macOS may still hide it (see the top of this file).
    """
    command = argv(method, title, subtitle, message, which)
    if not command:
        return True, "notifications are off (notifications.method = none)"
    try:
        done = runner(command)
    except (FileNotFoundError, OSError):
        return False, f"{command[0]} was not found"
    if done.returncode != 0:
        lines = (done.stderr or "").strip().splitlines()
        return False, lines[-1] if lines else f"{command[0]} exit code {done.returncode}"
    return True, f"sent with {resolve(method, which)[0]}"


def script_line(method: str, name: str, which=shutil.which) -> str:
    """One line of shell for the end of a background script. `$msg` holds the text ("finished" ...)."""
    kind, path = resolve(method, which)
    title = "mylauncher: " + "".join(c for c in name if c not in '"\\$`\n')
    if kind == "none":
        return ":"
    if kind == "terminal-notifier":
        return f'{shlex.quote(path)} -title {shlex.quote(title)} -message "$msg" -group mylauncher >/dev/null 2>&1'
    return f'/usr/bin/osascript -e "display notification \\"$msg\\" with title \\"{title}\\"" >/dev/null 2>&1'
