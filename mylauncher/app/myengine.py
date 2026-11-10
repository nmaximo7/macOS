"""
myengine.py - how the window talks to the engine in cli/.

The window never searches or runs anything by itself. For each thing it needs, it starts the
command line program as a separate process, exactly as you would type it in Terminal:

    python3 cli/mylauncher.py search obs --json          -> suggestions
    python3 cli/mylauncher.py run --id app:Obsidian --yes --json   -> do it

and reads the JSON that comes back. This is the "clear separation" rule of the project: you can
always reproduce what the window does by typing the same line in Terminal.

The `runner` argument (default: subprocess.run) can be replaced in tests by a fake one.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

CLI_SCRIPT = Path(__file__).resolve().parent.parent / "cli" / "mylauncher.py"
TIMEOUT = 15  # seconds; a launcher that hangs is worse than one that says "error"


class EngineError(Exception):
    """The engine could not be started or answered something we cannot understand."""


class Engine:
    def __init__(self, config_path=None, runner=subprocess.run, python=None, script=CLI_SCRIPT):
        self.config_path = config_path
        self.runner = runner
        self.python = python or sys.executable
        self.script = str(script)

    def _call(self, subcommand: str, *rest) -> dict:
        """Run `mylauncher.py <subcommand> --json [--config F] <rest>` and return the JSON as a dictionary."""
        command = [self.python, self.script, subcommand, "--json"]
        if self.config_path:
            command += ["--config", str(self.config_path)]
        command += rest
        try:
            done = self.runner(command, capture_output=True, text=True, timeout=TIMEOUT)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise EngineError(f"cannot run the engine: {exc}") from None
        # Note: the engine uses exit code 1 for "no match" and still prints valid JSON, so we
        # read stdout whatever the exit code is, and only complain when it is not JSON.
        try:
            return json.loads(done.stdout)
        except json.JSONDecodeError:
            detail = (done.stderr or done.stdout or "no output").strip().splitlines()[-1:]
            raise EngineError(f"the engine answered something unexpected: {detail[0] if detail else ''}") from None

    def search(self, text: str) -> dict:
        """{"query": ..., "completion": ..., "results": [item dictionaries with a score]}"""
        # "--" = "everything after this is text, not an option": so typing "-x" cannot confuse the engine.
        data = self._call("search", *(["--", text] if text.strip() else []))
        if "error" in data:
            raise EngineError(data["error"])
        return data

    def run(self, item_id: str) -> tuple:
        """Do an item. Returns (ok, message). The window has already asked for confirmation, hence --yes."""
        data = self._call("run", "--id", item_id, "--yes")
        if "error" in data:
            return False, data["error"]
        return data["result"]["ok"], data["result"]["message"]
