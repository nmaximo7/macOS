#!/usr/bin/env python3
"""
myautostart.py - start mylauncher automatically when you log in (a macOS "launch agent").

    app/mylauncher-autostart show        print the file and the commands, change nothing
    app/mylauncher-autostart install     write the agent and start it now (and at every login)
    app/mylauncher-autostart status      is it loaded? running? which process?
    app/mylauncher-autostart logs        the last lines of the log file
    app/mylauncher-autostart restart     stop and start it (after editing the configuration)
    app/mylauncher-autostart uninstall   stop it and remove the agent
Option: --dry-run (install / uninstall / restart: show, do nothing), --config FILE.

How it works. macOS has a program called launchd that starts and watches programs for you. You
describe a program in a small XML file (a "property list", .plist) saved in ~/Library/LaunchAgents/;
launchd reads that folder at login. We write that file (plistlib, from Python's standard library),
and talk to launchd with the command `launchctl`:

    launchctl bootstrap gui/<your user id> <file.plist>     load it (starts it, RunAtLoad)
    launchctl bootout   gui/<your user id>/<label>          unload it (stops it)
    launchctl print     gui/<your user id>/<label>          ask about it
    launchctl kickstart -k gui/<your user id>/<label>       restart it

"gui/<id>" = "the graphical session of this user": needed because we draw a window.

PERMISSIONS CHANGE when launchd starts us. Started from Ghostty, macOS credits the permissions
(Accessibility, Input Monitoring) to Ghostty. Started by launchd there is no terminal, so they
are checked against the Python program itself. `install` prints which file to add.
"""

from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cli"))

from myconfig import ConfigError, find_config_path, load_config  # noqa: E402

APP_SCRIPT = Path(__file__).resolve().parent / "mylauncher_app.py"
WORK_DIR = Path(__file__).resolve().parent.parent


def plist_path(config, home: Path | None = None) -> Path:
    return (home or Path.home()) / "Library" / "LaunchAgents" / f"{config.autostart_label}.plist"


def build_plist(config, python: str, config_path: Path) -> dict:
    """The content of the agent file, as a dictionary (plistlib turns it into XML)."""
    log = str(config.autostart_log_dir / "mylauncher.log")
    agent = {
        "Label": config.autostart_label,
        # The command launchd runs: exactly what you would type in Terminal, with absolute paths.
        "ProgramArguments": [python, str(APP_SCRIPT), "--config", str(Path(config_path).resolve())],
        "WorkingDirectory": str(WORK_DIR),
        "RunAtLoad": True,  # start as soon as the agent is loaded (at login, or at `install`)
        "LimitLoadToSessionType": "Aqua",  # only in a graphical login: we need a screen
        "ProcessType": "Interactive",  # tell macOS this is a user-facing program (do not slow it down)
        "EnvironmentVariables": {"PYTHONUNBUFFERED": "1"},  # write log lines at once, not in big delayed blocks
        "StandardOutPath": log,
        "StandardErrorPath": log,
    }
    if config.autostart_keep_alive:
        # Restart it if it CRASHES (exit code not 0); a clean exit (Ctrl+C) leaves it stopped.
        agent["KeepAlive"] = {"SuccessfulExit": False}
    return agent


def real_python(python: str) -> str:
    """.venv/bin/python is a link; macOS permissions are checked against the real file."""
    return os.path.realpath(python)


def default_runner(command):
    return subprocess.run(command, capture_output=True, text=True, timeout=30)


class Autostart:
    """Everything that touches the system is here, with the runner, home and user id injectable."""

    def __init__(self, config, config_path, python=None, runner=default_runner, home=None, uid=None, dry_run=False):
        self.config, self.config_path = config, Path(config_path)
        self.python = python or sys.executable
        self.runner, self.home, self.dry_run = runner, home, dry_run
        self.uid = os.getuid() if uid is None else uid

    # ---- names ----------------------------------------------------------- #
    @property
    def domain(self) -> str:
        return f"gui/{self.uid}"

    @property
    def service(self) -> str:
        return f"{self.domain}/{self.config.autostart_label}"

    @property
    def file(self) -> Path:
        return plist_path(self.config, self.home)

    @property
    def log_file(self) -> Path:
        return self.config.autostart_log_dir / "mylauncher.log"

    def plist_bytes(self) -> bytes:
        return plistlib.dumps(build_plist(self.config, self.python, self.config_path))

    # ---- launchctl ------------------------------------------------------- #
    def _launchctl(self, *arguments):
        command = ["launchctl", *arguments]
        if self.dry_run:
            return None, f"would run: {' '.join(command)}"
        try:
            done = self.runner(command)
        except FileNotFoundError:
            raise RuntimeError("'launchctl' was not found: this only works on macOS") from None
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"'{' '.join(command)}' took too long") from None
        return done, f"ran: {' '.join(command)}"

    def is_loaded(self) -> bool:
        done, _ = self._launchctl("print", self.service)
        return bool(done and done.returncode == 0)

    # ---- the commands ---------------------------------------------------- #
    def install(self) -> list:
        lines = []
        if self.dry_run:
            lines += [f"would write {self.file}", self.plist_bytes().decode()]
        else:
            self.config.autostart_log_dir.mkdir(parents=True, exist_ok=True)
            self.file.parent.mkdir(parents=True, exist_ok=True)
            self.file.write_bytes(self.plist_bytes())
            lines.append(f"wrote {self.file}")
        if not self.dry_run and self.is_loaded():  # re-installing: unload the old version first
            lines.append(self._launchctl("bootout", self.service)[1])
        done, text = self._launchctl("bootstrap", self.domain, str(self.file))
        lines.append(text)
        if done is not None and done.returncode != 0:
            raise RuntimeError(f"launchctl bootstrap failed: {(done.stderr or done.stdout).strip()}")
        lines += [
            "",
            "PERMISSIONS: when started at login there is no terminal, so macOS checks the Python program itself.",
            "In System Settings → Privacy & Security, in BOTH Accessibility (device control) and Input Monitoring, add:",
            f"    {real_python(self.python)}",
            f"Then:  {Path(sys.argv[0]).name} restart      and look at:  logs",
        ]
        return lines

    def uninstall(self) -> list:
        lines = []
        if self.dry_run or self.is_loaded():
            lines.append(self._launchctl("bootout", self.service)[1])
        if self.file.exists():
            if self.dry_run:
                lines.append(f"would delete {self.file}")
            else:
                self.file.unlink()
                lines.append(f"deleted {self.file}")
        elif not lines:
            lines.append("nothing to uninstall")
        return lines

    def restart(self) -> list:
        done, text = self._launchctl("kickstart", "-k", self.service)
        if done is not None and done.returncode != 0:
            raise RuntimeError("could not restart (is it installed? try: install)")
        return [text]

    def status(self) -> list:
        lines = [f"agent file: {self.file} ({'exists' if self.file.exists() else 'MISSING: run install'})"]
        done, _ = self._launchctl("print", self.service)
        if done is None or done.returncode != 0:
            return [*lines, "launchd: not loaded (it will start at the next login if the file exists)"]
        info = {}
        for line in done.stdout.splitlines():
            key, sep, value = line.strip().partition(" = ")
            if sep and key in ("state", "pid", "last exit code", "runs"):
                info[key] = value
        lines.append("launchd: loaded, " + ", ".join(f"{k} {v}" for k, v in info.items()))
        lines.append(f"log: {self.log_file}")
        return lines

    def logs(self, count: int = 30) -> list:
        if not self.log_file.exists():
            return [f"no log yet: {self.log_file}"]
        return self.log_file.read_text(encoding="utf-8", errors="replace").splitlines()[-count:]


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mylauncher-autostart", description="start mylauncher at login")
    parser.add_argument("command", choices=["show", "install", "uninstall", "restart", "status", "logs"])
    parser.add_argument("--config", metavar="FILE")
    parser.add_argument("--dry-run", action="store_true", help="show what would happen, do nothing")
    return parser


def main(argv=None, runner=default_runner, home=None, uid=None, python=None) -> int:
    args = make_parser().parse_args(argv)
    config_path = find_config_path(args.config)
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    auto = Autostart(config, config_path, python=python, runner=runner, home=home, uid=uid, dry_run=args.dry_run)
    try:
        if args.command == "show":
            lines = [f"file: {auto.file}", auto.plist_bytes().decode(), f"load:   launchctl bootstrap {auto.domain} {auto.file}",
                     f"unload: launchctl bootout {auto.service}"]
        else:
            lines = getattr(auto, args.command)()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
