"""
myactions.py - the only file that DOES things to the Mac.

The actions:

    open_app   open an application          (uses the macOS command  open /Applications/X.app)
    shutdown   shut the Mac down            (uses  osascript  to ask the system politely)
    open_url   open a web address           (uses  open <url>: your default browser)
    kill_app   close a running application  (ask it to quit; if it does not, force quit; see below)
    copy_snippet copy a text to the clipboard (pbcopy) and show a notification (osascript)
    prefix_hint  not a real action: a word that needs more text after it (the window completes it)

Safety rules built in from day one:
  * dry_run=True never runs anything: it only says what WOULD be run. Perfect for learning.
  * Every command goes through a "runner" function. In normal life the runner really runs the
    command; in the tests we give a fake one, so tests can never shut your Mac down.

Why `osascript` for shutdown? `sudo shutdown -h now` needs the administrator password and closes
everything brutally. `tell application "System Events" to shut down` is what the Apple menu does:
apps are asked to quit and may ask you to save your work.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from mykill import alive, applescript_quote, running_apps
from mytypes import Item

# Actions that a "command" in the configuration file may use. (Apps always use open_app.)
COMMAND_ACTIONS = ("shutdown",)


@dataclass
class ActionResult:
    """What happened: ok (True/False), a sentence for humans, and the command that was (or would be) run."""

    ok: bool
    message: str
    command: list
    needs_force: bool = False  # True: "it did not quit; ask the user, then run again with force"

    def to_dict(self) -> dict:
        return {"ok": self.ok, "message": self.message, "command": self.command, "needs_force": self.needs_force}


@dataclass
class RunOptions:
    """Extra settings some actions use (kill_app and copy_snippet). Everything has a default."""

    force: bool = False  # kill: skip the polite request, force quit now
    grace: float = 5  # kill: seconds to wait for the app to quit by itself
    auto_force: bool = False  # kill: force quit without asking when it did not quit
    sleep: object = field(default=time.sleep, repr=False)  # replaced in tests so they do not really wait
    notify: bool = True  # copy_snippet: show a macOS notification


def default_runner(command: list, input_text: str | None = None) -> subprocess.CompletedProcess:
    """Really run a command and capture its output. `check=False`: we look at the exit code ourselves.

    `input_text` (optional) is sent to the command's standard input, like  echo text | command.
    We send it as UTF-8 and tell the command LANG=en_US.UTF-8: when macOS starts us at login there is
    no language setting, and `pbcopy` would then garble accents and emoji.
    """
    env = {**os.environ, "LANG": "en_US.UTF-8"} if input_text is not None else None
    return subprocess.run(
        command, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace", input=input_text, env=env
    )


def _execute(command: list, runner, dry_run: bool, done: str) -> ActionResult:
    """Run `command` through `runner` (or just describe it when dry_run) and report the result."""
    if dry_run:
        return ActionResult(True, "dry run, nothing was done. Would run: " + shlex.join(command), command)
    try:
        completed = runner(command)
    except FileNotFoundError:
        return ActionResult(False, f"the program '{command[0]}' was not found (is this a Mac?)", command)
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip() or f"exit code {completed.returncode}"
        return ActionResult(False, f"failed: {detail}", command)
    return ActionResult(True, done, command)


def open_app(item: Item, runner=default_runner, dry_run: bool = False, options=None) -> ActionResult:
    """Open the application stored in item.target."""
    command = ["open", item.target]
    if not dry_run and not Path(item.target).exists():
        return ActionResult(False, f"{item.target} does not exist any more (moved or uninstalled?)", command)
    return _execute(command, runner, dry_run, f"opened {item.title.removeprefix('Run ')}")


def shutdown(item: Item, runner=default_runner, dry_run: bool = False, options=None) -> ActionResult:
    """Ask macOS to shut down (like the Apple menu > Shut Down)."""
    command = ["osascript", "-e", 'tell application "System Events" to shut down']
    return _execute(command, runner, dry_run, "shutting down...")


def open_url(item: Item, runner=default_runner, dry_run: bool = False, options=None) -> ActionResult:
    """Open the web address stored in item.target in the default browser."""
    command = ["open", item.target]
    if not item.target.startswith(("http://", "https://")):  # never hand anything else to `open`
        return ActionResult(False, f"refusing to open {item.target!r}: only http:// and https:// addresses", command)
    return _execute(command, runner, dry_run, f"opened {item.target}")


def prefix_hint(item: Item, runner=default_runner, dry_run: bool = False, options=None) -> ActionResult:
    """Items like "yt" or "kill" need text after them; pressing Enter on them only explains that."""
    return ActionResult(False, f"type something after it, for example:  {item.complete}...", [])


NOTIFICATION_WIDTH = 120  # a notification shows only a few lines: cut long texts


def copy_snippet(item: Item, runner=default_runner, dry_run: bool = False, options=None) -> ActionResult:
    """Copy item.target (the snippet text) to the clipboard, then show a notification.

    * Clipboard: `pbcopy` reads its standard input and puts it in the clipboard (macOS command).
    * Notification: `osascript -e 'display notification ...'`. It is a courtesy: if it fails (for
      example notifications are blocked for "Script Editor" in System Settings), the text is
      already copied, so the action still counts as done.
    """
    options = options or RunOptions()
    command = ["pbcopy"]
    count = len(item.target)
    if dry_run:
        return ActionResult(True, f"dry run, nothing was done. Would copy {count} characters with pbcopy" + (" and show a notification" if options.notify else ""), command)
    try:
        done = runner(command, input_text=item.target)
    except FileNotFoundError:
        return ActionResult(False, "the program 'pbcopy' was not found (is this a Mac?)", command)
    if done.returncode != 0:
        return ActionResult(False, f"could not copy: {(done.stderr or '').strip() or f'exit code {done.returncode}'}", command)
    message = f"{item.title} copied to the clipboard ({count} characters)"
    if options.notify:
        shown = item.subtitle[:NOTIFICATION_WIDTH] or item.target[:NOTIFICATION_WIDTH]
        script = (
            f'display notification "{applescript_quote(shown)}" with title "mylauncher" '
            f'subtitle "{applescript_quote(item.title)} copied to the clipboard"'
        )
        try:
            runner(["osascript", "-e", script])
        except (FileNotFoundError, OSError):
            pass  # no notification, but the text IS in the clipboard
    return ActionResult(True, message, command)


POLL_SECONDS = 0.25  # how often kill_app looks whether the app is gone


def kill_app(item: Item, runner=default_runner, dry_run: bool = False, options=None) -> ActionResult:
    """Close a running application, politely first.

    1. Ask it to quit, like Cmd+Q:  osascript -e 'tell application "<path>" to quit'.
       (If macOS refuses that, for example the Automation permission was denied, we fall back
       to  kill -TERM <pids>, the ordinary "please stop".)
    2. Wait up to `grace` seconds for it to disappear.
    3. Still there? It is frozen, or it is asking "save your changes?". Then:
         * options.auto_force  -> kill -KILL straight away (force quit);
         * otherwise we do NOT do it ourselves: we answer needs_force=True, the caller asks you,
           and calls again with options.force=True, which goes directly to kill -KILL.
       Force quit loses unsaved work, which is why it is not the silent default.
    """
    options = options or RunOptions()
    name = item.title.removeprefix("Kill ")
    quit_command = ["osascript", "-e", f'tell application "{applescript_quote(item.target)}" to quit']
    if dry_run:
        text = f"dry run, nothing was done. Would run: {shlex.join(quit_command)}; if still running after {options.grace} s: kill -KILL <pids>"
        return ActionResult(True, text, quit_command)

    pids = [pid for app in running_apps(runner) if app.path == item.target for pid in app.pids]
    if not pids:
        return ActionResult(False, f"{name} is not running", quit_command)

    if not options.force:
        try:
            polite = runner(quit_command)
            if polite.returncode != 0:
                runner(["kill", "-TERM", *map(str, pids)])  # the fallback described above
        except FileNotFoundError:
            runner(["kill", "-TERM", *map(str, pids)])
        waited = 0.0
        while alive(runner, pids) and waited < options.grace:
            options.sleep(POLL_SECONDS)
            waited += POLL_SECONDS
        if not alive(runner, pids):
            return ActionResult(True, f"{name} quit", quit_command)
        if not options.auto_force:
            message = (
                f"{name} did not quit within {options.grace:g} s (frozen, or asking to save?). "
                "Run again with --force to force quit it (unsaved work is lost)."
            )
            return ActionResult(False, message, quit_command, needs_force=True)

    remaining = alive(runner, pids)
    force_command = ["kill", "-KILL", *map(str, remaining)]
    if remaining:
        runner(force_command)
        options.sleep(POLL_SECONDS)
    if alive(runner, pids):
        return ActionResult(False, f"could not force quit {name}", force_command)
    return ActionResult(True, f"{name} was force quit", force_command)


# The "phone book" of actions: the name written in an Item -> the function to call.
# To teach the launcher a new trick you write a function above and add one line here.
ACTIONS = {
    "open_app": open_app,
    "shutdown": shutdown,
    "open_url": open_url,
    "kill_app": kill_app,
    "prefix_hint": prefix_hint,
    "copy_snippet": copy_snippet,
}


def run_item(item: Item, runner=default_runner, dry_run: bool = False, options: RunOptions | None = None) -> ActionResult:
    """Do what the item says (look its action up in ACTIONS)."""
    function = ACTIONS.get(item.action)
    if function is None:
        return ActionResult(False, f"unknown action '{item.action}'", [])
    return function(item, runner=runner, dry_run=dry_run, options=options)
