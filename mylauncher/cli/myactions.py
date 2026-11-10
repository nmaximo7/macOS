"""
myactions.py - the only file that DOES things to the Mac.

Two actions exist for now:

    open_app   open an application          (uses the macOS command  open /Applications/X.app)
    shutdown   shut the Mac down            (uses  osascript  to ask the system politely)

Safety rules built in from day one:
  * dry_run=True never runs anything: it only says what WOULD be run. Perfect for learning.
  * Every command goes through a "runner" function. In normal life the runner really runs the
    command; in the tests we give a fake one, so tests can never shut your Mac down.

Why `osascript` for shutdown? `sudo shutdown -h now` needs the administrator password and closes
everything brutally. `tell application "System Events" to shut down` is what the Apple menu does:
apps are asked to quit and may ask you to save your work.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from mytypes import Item

# Actions that a "command" in the configuration file may use. (Apps always use open_app.)
COMMAND_ACTIONS = ("shutdown",)


@dataclass
class ActionResult:
    """What happened: ok (True/False), a sentence for humans, and the command that was (or would be) run."""

    ok: bool
    message: str
    command: list

    def to_dict(self) -> dict:
        return {"ok": self.ok, "message": self.message, "command": self.command}


def default_runner(command: list) -> subprocess.CompletedProcess:
    """Really run a command and capture its output. `check=False`: we look at the exit code ourselves."""
    return subprocess.run(command, check=False, capture_output=True, text=True)


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


def open_app(item: Item, runner=default_runner, dry_run: bool = False) -> ActionResult:
    """Open the application stored in item.target."""
    command = ["open", item.target]
    if not dry_run and not Path(item.target).exists():
        return ActionResult(False, f"{item.target} does not exist any more (moved or uninstalled?)", command)
    return _execute(command, runner, dry_run, f"opened {item.title.removeprefix('Run ')}")


def shutdown(item: Item, runner=default_runner, dry_run: bool = False) -> ActionResult:
    """Ask macOS to shut down (like the Apple menu > Shut Down)."""
    command = ["osascript", "-e", 'tell application "System Events" to shut down']
    return _execute(command, runner, dry_run, "shutting down...")


# The "phone book" of actions: the name written in an Item -> the function to call.
# To teach the launcher a new trick you write a function above and add one line here.
ACTIONS = {
    "open_app": open_app,
    "shutdown": shutdown,
}


def run_item(item: Item, runner=default_runner, dry_run: bool = False) -> ActionResult:
    """Do what the item says (look its action up in ACTIONS)."""
    function = ACTIONS.get(item.action)
    if function is None:
        return ActionResult(False, f"unknown action '{item.action}'", [])
    return function(item, runner=runner, dry_run=dry_run)
