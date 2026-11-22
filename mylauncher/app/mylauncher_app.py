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
import dataclasses
import faulthandler
import os
import queue
import signal
import sys
import time
from pathlib import Path

# The app reads the settings through the same code as the CLI (cli/myconfig.py), so a mistake in the
# JSON is reported in exactly the same way. Everything else goes through the command line engine.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cli"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from myconfig import ConfigError, find_config_path, load_config  # noqa: E402
import mytimer  # noqa: E402
from myengine import Engine  # noqa: E402
from mymenubar import MenuBar  # noqa: E402
from myhotkey import HotkeyListener, describe, permission_report, watch_keys  # noqa: E402

POLL_MS = 100  # how often the main thread looks at the queue


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mylauncher_app", description="mylauncher window and hotkey")
    parser.add_argument("--config", metavar="FILE", help="configuration file")
    parser.add_argument("--show", action="store_true", help="show the window right away")
    parser.add_argument("--keep-old", action="store_true", help="if another copy is running, end THIS one (the default: the newest copy stops the old ones and takes over)")
    parser.add_argument("--toast-test", action="store_true", help="show the toast for 3 seconds, with the window hidden, and exit")
    parser.add_argument("--timer-test", action="store_true", help="a 6 second timer: big clock, then confetti, and exit")
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


def timer_test(config) -> int:
    """Try the big clock and the confetti without waiting for a real timer (6 seconds)."""
    import tkinter as tk
    from mytheme import make_theme
    from mytimerdisplay import TimerDisplay
    root = tk.Tk()
    root.withdraw()
    display = TimerDisplay(dataclasses.replace(config, timer_big_clock_seconds=60, timer_big_clock=True, timer_confetti=True), make_theme(config), root.after)
    start = time.time()

    def step():
        left = 6 - (time.time() - start)
        display.update([{"id": "test", "remaining": left}] if left > 0 else [], time.time())
        if left > -10:
            root.after(250 if left > 0 else 500, step)
        else:
            root.destroy()
    # the first call sees 6 s, the later ones count down; when 0 is reached the timer "vanishes" and the confetti starts
    step()
    root.mainloop()
    print("timer test finished")
    return 0


def toast_test(config) -> int:
    """Same situation as after a copy: the launcher window is hidden, then the toast appears."""
    import tkinter as tk
    from mytheme import make_theme
    from mytoast import Toast
    root = tk.Tk()
    root.withdraw()
    toast = Toast(root, make_theme(config), 3.0, config.window_top_offset)
    toast.show("✔  toast test: do you see this at the top of the screen?")
    print("toast shown with " + ("the Cocoa panel" if toast.panel is not None else "the Tk window (fallback)") + "; waiting 3 seconds")
    root.after(3500, root.destroy)
    root.mainloop()
    return 0


def hotkey_test(config) -> int:
    """No window: just prove that the permission and the key combination work."""
    print_permissions()
    name = describe(config.hotkey_modifiers, config.hotkey_key)
    listener = HotkeyListener(config.hotkey_modifiers, config.hotkey_key, lambda: print(f"hotkey {name} pressed"), swallow=config.hotkey_swallow)
    try:
        listener.start()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if config.hotkey_swallow:
        print(f"swallowing: {'yes, the application in front will NOT receive the keys' if listener.swallowing else 'NO (this pynput does not support darwin_intercept: pip install -U pynput)'}")
    print(f"Press {name} in any application. Nothing printed? See 'Permissions' in docs/01-installation.md. Ctrl+C to stop.")
    try:
        listener._listener.join()
    except KeyboardInterrupt:
        pass
    return 0


def run(config, config_path, show: bool, keep_old: bool = False) -> int:
    try:
        import tkinter as tk
    except ImportError:
        print("error: tkinter is missing. On macOS with Homebrew: brew install python-tk", file=sys.stderr)
        return 1
    from mywindow import LauncherWindow  # imported here because it needs tkinter

    import myinstance

    lock_path = config.usage_file.parent / "app.lock"
    lock, other = myinstance.acquire(lock_path)
    if keep_old and lock is None:
        print(f"mylauncher is already running (pid {other}); this second copy ends (--keep-old).", flush=True)
        return 0
    if not keep_old:  # the NEWEST copy wins: stop every old one (also the ones that do not hold the lock any more)
        if lock is not None:
            lock.close()  # (acquire wrote our pid; we take it again after the old copies are gone)
        stopped, forced = myinstance.stop_old_instances()
        if stopped:
            print(f"[app] stopped {len(stopped)} old copy(ies) of mylauncher: {stopped}" + (f" (SIGKILL for {forced})" if forced else ""), flush=True)
        for _ in range(20):
            lock, other = myinstance.acquire(lock_path)
            if lock is not None:
                break
            time.sleep(0.25)
        if lock is None:
            print(f"mylauncher: could not take over from pid {other}; this copy ends. Try: pkill -f mylauncher_app.py", flush=True)
            return 1

    def quit_now(signum, frame):  # `kill`, a newer copy of the launcher, launchd at shutdown: leave at once and CLEANLY (exit 0: launchd does not restart it)
        print(f"[app] signal {signum}: leaving", flush=True)
        os._exit(0)

    signal.signal(signal.SIGTERM, quit_now)  # runs at the next 1-second tick at the latest
    print(f"python: {sys.executable}", flush=True)  # these lines go to the log file when started at login
    print_permissions()
    root = tk.Tk()
    root.withdraw()  # start hidden: the hotkey shows it
    window = LauncherWindow(root, Engine(config_path=config_path), config)
    import mypoweroff
    from mypower import already_asked

    leaving = {"now": False}

    def power_off_started() -> None:
        print("[app] the Mac is restarting / shutting down / logging out: leaving at once", flush=True)
        leaving["now"] = True
        os._exit(0)  # no clean-up needed, and nothing may delay the restart

    power_watch = mypoweroff.watch(power_off_started)  # keep the reference: the observer lives as long as this variable
    protect_from_closing(root, window, log=lambda text: print(text, flush=True),
                         may_quit=lambda: leaving["now"] or already_asked(config.power_lock))

    messages: queue.Queue = queue.Queue()
    listener = HotkeyListener(config.hotkey_modifiers, config.hotkey_key, lambda: (print("[hotkey] pressed", flush=True), messages.put("toggle")), swallow=config.hotkey_swallow)
    try:
        listener.start()
    except RuntimeError as exc:
        print(f"warning: no hotkey ({exc}); use --show", file=sys.stderr)
    else:
        print(f"hotkey swallowing: {'on' if listener.swallowing else 'off'}", flush=True)
        listener.guard(log=lambda text: print(text, flush=True))

    def watchdog() -> None:
        """Every 2 s: if macOS switched the hotkey off (too many key events at once), start it again."""
        # Dead-man switch: faulthandler's own C thread (it needs no GIL) prints the stack of EVERY thread into the log
        # if this function does not run again within 8 s, i.e. if the window's event loop is stuck. That shows where.
        faulthandler.dump_traceback_later(8, repeat=False, file=sys.stderr)
        if not listener.healthy():
            print("[hotkey] the keyboard listener stopped (macOS switches it off after a flood of key events); restarting it", flush=True)
            try:
                listener.restart()
            except Exception as exc:  # noqa: BLE001 - try again at the next beat
                print(f"[hotkey] restart failed: {exc}", file=sys.stderr, flush=True)
        root.after(2000, watchdog)

    root.after(2000, watchdog)

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

    from mytheme import make_theme
    from mytimerdisplay import TimerDisplay
    display = TimerDisplay(config, make_theme(config), root.after)
    shown_title = [None]

    def tick() -> None:
        """Every second: the window's countdown rows, and the menu bar title (the soonest timer: ⏱ 00:02:59)."""
        try:
            now = time.time()
            window.tick(now)
            timers = mytimer.running(config.timer_folder, now)
            display.update(timers, now)
            if bar is not None:
                title = f"⏱ {mytimer.clock(timers[0]['remaining'])}" if timers else config.menubar_title
                if title != shown_title[0]:
                    shown_title[0] = title
                    bar.set_title(title)
        except Exception:  # noqa: BLE001 - the clock must never stop the launcher
            pass
        root.after(1000, tick)

    root.after(1000, tick)

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
            try:
                print(f"[poll] {message}: handling", flush=True)
                window.toggle()
                print(f"{message} received: window {'shown' if window.visible else 'hidden'}", flush=True)  # proof that each step worked
            except Exception:  # noqa: BLE001 - one failure must never end the polling: the hotkey would be dead for ever
                import traceback
                print(f"[window] {message} failed:\n{traceback.format_exc()}", file=sys.stderr, flush=True)
                try:
                    window.hide()
                except Exception:  # noqa: BLE001
                    pass
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
        print("[app] the main loop ended", flush=True)  # if this line is the last one in the log, the loop returned by itself
        listener.stop()
        if bar is not None:
            bar.stop()
    return 0


def protect_from_closing(root, window, log=print, may_quit=lambda: False) -> None:
    """The program must only end when the user chooses "Quit" in the menu bar icon.

    Found on a real Mac (step 9i): after an action the program ended with exit code 0 and launchd, which restarts only
    after a CRASH, left it dead. Tk ends the program by itself when the window is asked to close, and when macOS sends
    the "quit" Apple event. Both are answered here: logged, and ignored.
    """
    def ignore_close():
        log("[app] a request to CLOSE the window was ignored (the window is hidden instead)")
        window.hide()

    def ignore_quit(*_):
        if may_quit():  # the Mac is restarting / shutting down / logging out: do not be the one that says "no"
            log("[app] a QUIT request from macOS during a restart / shutdown: leaving")
            root.quit()
            return
        log("[app] a QUIT request from macOS was ignored (use the menu bar icon > Quit mylauncher to quit)")

    root.protocol("WM_DELETE_WINDOW", ignore_close)
    root.createcommand("::tk::mac::Quit", ignore_quit)


def log_exit_calls() -> None:
    """Print the Python stack whenever something calls sys.exit(): that names the culprit if it is Python code."""
    import traceback

    def hook(event, args):
        if event == "sys.exit":
            print(f"[app] sys.exit({args[0]!r}) called from:\n{''.join(traceback.format_stack(limit=12))}", flush=True)

    try:
        sys.addaudithook(hook)
    except Exception:  # noqa: BLE001
        pass


def enable_stack_dumps() -> None:
    """Crash dumps, and `kill -USR1 <pid>` prints the stacks of all threads into the log (for a program that hangs)."""
    try:
        faulthandler.enable(file=sys.stderr, all_threads=True)
        faulthandler.register(signal.SIGUSR1, file=sys.stderr, all_threads=True)
        for name in ("SIGTERM", "SIGHUP", "SIGQUIT"):  # who stops us: print the stacks, then let the signal do its job
            faulthandler.register(getattr(signal, name), file=sys.stderr, all_threads=True, chain=True)
        import atexit

        atexit.register(lambda: print("[app] the program is exiting", flush=True))
    except (AttributeError, ValueError, OSError):
        pass  # not available here: the launcher works without


def main(argv=None) -> int:
    args = make_parser().parse_args(argv)
    config_path = find_config_path(args.config)
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    enable_stack_dumps()
    log_exit_calls()
    if args.keys:
        return keys_test()
    if args.toast_test:
        return toast_test(config)
    if args.timer_test:
        return timer_test(config)
    return hotkey_test(config) if args.hotkey_test else run(config, config_path, args.show, args.keep_old)


if __name__ == "__main__":
    sys.exit(main())
