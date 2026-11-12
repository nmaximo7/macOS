#!/usr/bin/env python3
"""
mylauncher_app.py - starts the launcher: the window plus the global hotkey.

    python3 app/mylauncher_app.py                 start; press the hotkey (Command+D by default)
    python3 app/mylauncher_app.py --show          also show the window at start (to try it without the hotkey)
    python3 app/mylauncher_app.py --hotkey-test   only test the hotkey: prints a line each time you press it
    python3 app/mylauncher_app.py --keys          print every key pressed (diagnose permissions)
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
from mymenubar import MenuBar  # noqa: E402
from myhotkey import HotkeyListener, describe, permission_report, watch_keys  # noqa: E402

POLL_MS = 100  # how often the main thread looks at the queue


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mylauncher_app", description="mylauncher window and hotkey")
    parser.add_argument("--config", metavar="FILE", help="configuration file")
    parser.add_argument("--show", action="store_true", help="show the window right away")
    parser.add_argument("--hotkey-test", action="store_true", help="only print a line when the hotkey is pressed")
    parser.add_argument("--keys", action="store_true", help="print EVERY key the program can see (to diagnose permissions)")
    return parser


def print_permissions() -> None:
    for symbol, text in permission_report():
        print(f" {symbol} {text}")


def keys_test() -> int:
    """No window, no hotkey: print every key. The simplest way to know if macOS lets us see the keyboard."""
    print(f"python: {sys.executable}")
    print_permissions()
    try:
        listener = watch_keys()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print("Press any keys, in any application. Nothing printed = permissions. Ctrl+C to stop.")
    try:
        listener.join()
    except KeyboardInterrupt:
        pass
    return 0


def hotkey_test(config) -> int:
    """No window: just prove that the permission and the key combination work."""
    print_permissions()
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

    print(f"python: {sys.executable}", flush=True)  # these lines go to the log file when started at login
    print_permissions()
    root = tk.Tk()
    root.withdraw()  # start hidden: the hotkey shows it
    window = LauncherWindow(root, Engine(config_path=config_path), config)

    messages: queue.Queue = queue.Queue()
    listener = HotkeyListener(config.hotkey_modifiers, config.hotkey_key, lambda: messages.put("toggle"))
    try:
        listener.start()
    except RuntimeError as exc:
        print(f"warning: no hotkey ({exc}); use --show", file=sys.stderr)

    bar = None
    if config.menubar_enabled:
        # The menu bar icon talks to the main loop through the same queue as the hotkey.
        bar = MenuBar(config.menubar_title, messages.put, hide_dock=config.menubar_hide_dock)
        try:
            bar.start()
            print(f"menu bar icon: {config.menubar_title}", flush=True)
        except Exception as exc:  # noqa: BLE001 - a missing icon must never stop the launcher
            print(f"warning: no menu bar icon ({exc})", file=sys.stderr, flush=True)
            bar = None

    def poll() -> None:
        while True:
            try:
                message = messages.get_nowait()
            except queue.Empty:
                break
            if message == "quit":
                print("quit chosen in the menu bar", flush=True)
                root.quit()
                return
            window.toggle()
            print(f"{message} received: window {'shown' if window.visible else 'hidden'}", flush=True)  # proof that each step worked
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
        if bar is not None:
            bar.stop()
    return 0


def main(argv=None) -> int:
    args = make_parser().parse_args(argv)
    config_path = find_config_path(args.config)
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.keys:
        return keys_test()
    return hotkey_test(config) if args.hotkey_test else run(config, config_path, args.show)


if __name__ == "__main__":
    sys.exit(main())
