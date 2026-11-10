#!/usr/bin/env python3
"""
mylauncher_app.py - starts the launcher: the window plus the global hotkey.

    python3 app/mylauncher_app.py                 start; press the hotkey (Command+D by default)
    python3 app/mylauncher_app.py --show          also show the window at start (to try it without the hotkey)
    python3 app/mylauncher_app.py --hotkey-test   only test the hotkey: prints a line each time you press it
    python3 app/mylauncher_app.py --config FILE   another configuration file

How threads fit together (the one tricky part of this project):

    pynput thread  --(hotkey pressed)-->  queue  --(polled every 100 ms)-->  main thread  -> window.toggle()

tkinter can only be used from the main thread, so the hotkey callback does not touch the window; it
just drops a message in a queue, and the main thread looks at the queue 10 times per second.
"""

from __future__ import annotations

import argparse
import os
import queue
import sys
from pathlib import Path

# The app reads the settings through the same code as the CLI (cli/myconfig.py), so a mistake in the
# JSON is reported in exactly the same way. Everything else goes through the command line engine.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cli"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from myconfig import ConfigError, find_config_path, load_config  # noqa: E402
from myengine import Engine  # noqa: E402
from myhotkey import HotkeyListener, describe  # noqa: E402

POLL_MS = 100  # how often the main thread looks at the queue


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mylauncher_app", description="mylauncher window and hotkey")
    parser.add_argument("--config", metavar="FILE", help="configuration file")
    parser.add_argument("--show", action="store_true", help="show the window right away")
    parser.add_argument("--hotkey-test", action="store_true", help="only print a line when the hotkey is pressed")
    return parser


def hotkey_test(config) -> int:
    """No window: just prove that the permission and the key combination work."""
    name = describe(config.hotkey_modifiers, config.hotkey_key)
    listener = HotkeyListener(config.hotkey_modifiers, config.hotkey_key, lambda: print(f"hotkey {name} pressed"))
    try:
        listener.start()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Press {name} in any application. Nothing printed? See 'Permissions' in docs/01-installation.md. Ctrl+C to stop.")
    try:
        listener._listener.join()
    except KeyboardInterrupt:
        pass
    return 0


def run(config, config_path, show: bool) -> int:
    try:
        import tkinter as tk
    except ImportError:
        print("error: tkinter is missing. On macOS with Homebrew: brew install python-tk", file=sys.stderr)
        return 1
    from mywindow import LauncherWindow  # imported here because it needs tkinter

    root = tk.Tk()
    root.withdraw()  # start hidden: the hotkey shows it
    window = LauncherWindow(root, Engine(config_path=config_path), config)

    messages: queue.Queue = queue.Queue()
    listener = HotkeyListener(config.hotkey_modifiers, config.hotkey_key, lambda: messages.put("toggle"))
    try:
        listener.start()
    except RuntimeError as exc:
        print(f"warning: no hotkey ({exc}); use --show", file=sys.stderr)

    def poll() -> None:
        while True:
            try:
                messages.get_nowait()
            except queue.Empty:
                break
            window.toggle()
        root.after(POLL_MS, poll)

    if show:
        window.show()
    print(f"mylauncher running. Hotkey: {describe(config.hotkey_modifiers, config.hotkey_key)}. Ctrl+C here to quit.")
    root.after(POLL_MS, poll)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        listener.stop()
    return 0


def main(argv=None) -> int:
    args = make_parser().parse_args(argv)
    config_path = find_config_path(args.config)
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return hotkey_test(config) if args.hotkey_test else run(config, config_path, args.show)


if __name__ == "__main__":
    sys.exit(main())
