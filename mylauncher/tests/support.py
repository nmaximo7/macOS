"""Shared helpers for the tests (no test cases in here)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "cli"
APP = ROOT / "app"
for folder in (CLI, APP):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))  # so that "import myconfig" works, exactly as when the scripts run

REAL_CONFIG = ROOT / "conf" / "myconfiguration.json"


def good_config(folders=(), **changes) -> dict:
    """A valid configuration as a dictionary; `changes` replaces top-level sections."""
    data = {
        "hotkey": {"modifiers": ["command", "shift"], "key": "d"},
        "apps": {"folders": [str(f) for f in folders], "exclude": []},
        "search": {"max_results": 8, "ignore_accents": True, "fuzzy": True},
        # History OFF by default, so no test can ever write into the real ~/Library (tests that need it switch it on with a tmp file).
        "usage": {"enabled": False},
        "commands": [
            {"id": "shutdown", "title": "Shutdown", "action": "shutdown", "keywords": ["power off"], "confirm": True}
        ],
    }
    data.update(changes)
    return data


class TempDirCase(unittest.TestCase):
    """A test case with a fresh temporary folder in self.tmp (deleted afterwards)."""

    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.tmp = Path(holder.name)

    def make_apps(self, folder: str, *names: str) -> Path:
        """Create fake applications (empty folders called X.app) and return their parent folder."""
        parent = self.tmp / folder
        parent.mkdir(parents=True, exist_ok=True)
        for name in names:
            (parent / f"{name}.app").mkdir(exist_ok=True)
        return parent

    def write_quicklinks(self, data) -> Path:
        """Write quicklinks.json next to config.json (where the default setting looks for it)."""
        path = self.tmp / "quicklinks.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def write_config(self, data: dict) -> Path:
        path = self.tmp / "config.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path


class FakeRunner:
    """Replaces "really run a command": it only remembers what it was asked to run."""

    def __init__(self, returncode: int = 0, stderr: str = "", error: Exception | None = None):
        self.calls, self.inputs = [], []  # inputs = the text sent to a command's standard input (pbcopy)
        self.returncode, self.stderr, self.error = returncode, stderr, error

    def __call__(self, command, input_text=None):
        self.calls.append(command)
        if input_text is not None:
            self.inputs.append(input_text)
        if self.error:
            raise self.error
        from types import SimpleNamespace

        return SimpleNamespace(returncode=self.returncode, stderr=self.stderr, stdout="")


class FakeSystem:
    """A tiny pretend Mac for the kill tests: processes, `ps`, `osascript ... quit` and `kill`.

    apps: {"/Applications/Obsidian.app": [812, 813]}  (the pids of each application)
    quits:       does a polite "quit" make the app disappear?
    term_works:  does kill -TERM make it disappear? (kill -KILL always does)
    osascript_fails: pretend macOS refuses the Apple event (Automation permission denied)
    """

    def __init__(self, apps=None, quits=True, term_works=True, osascript_fails=False):
        self.procs = {}  # pid -> full command line, like `ps` prints it
        for path, pids in (apps or {}).items():
            name = path.rsplit("/", 1)[-1].removesuffix(".app")
            for pid in pids:
                self.procs[pid] = f"{path}/Contents/MacOS/{name} --flag"
        self.quits, self.term_works, self.osascript_fails = quits, term_works, osascript_fails
        self.calls = []
        self.clipboard = None

    def add_noise(self):
        """Processes that must NOT be listed: a helper inside an app, the Dock, a plain program."""
        self.procs[900] = "/Applications/Chrome.app/Contents/Frameworks/Helper.app/Contents/MacOS/Helper --type=gpu"
        self.procs[901] = "/System/Library/CoreServices/Dock.app/Contents/MacOS/Dock"
        self.procs[902] = "/usr/sbin/cfprefsd agent"

    def __call__(self, command, input_text=None):
        from types import SimpleNamespace

        self.calls.append(command)
        if input_text is not None:
            self.clipboard = input_text  # pbcopy
        done = lambda rc=0, out="", err="": SimpleNamespace(returncode=rc, stdout=out, stderr=err)  # noqa: E731
        program = command[0]
        if program == "ps" and command[1] == "-axo":
            return done(out="".join(f"{pid:>6} {cmd}\n" for pid, cmd in self.procs.items()))
        if program == "ps" and command[1] == "-p":
            wanted = [int(p) for p in command[2].split(",")]
            return done(out="".join(f"{pid:>6}\n" for pid in wanted if pid in self.procs))
        if program == "osascript":
            if self.osascript_fails:
                return done(1, err="execution error: Not authorized to send Apple events (-1743)")
            if self.quits:
                path = command[2].split('"')[1]
                for pid in [p for p, c in self.procs.items() if c.startswith(path + "/")]:
                    del self.procs[pid]
            return done()
        if program == "kill":
            killed = command[1] == "-KILL" or (command[1] == "-TERM" and self.term_works)
            if killed:
                for pid in command[2:]:
                    self.procs.pop(int(pid), None)
            return done()
        return done()  # "open" and anything else: success
