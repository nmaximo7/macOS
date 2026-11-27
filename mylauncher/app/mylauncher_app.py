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

GUIDED TOUR (for someone who is just starting to program) ---------------------------------------------------------------
This file is the CONDUCTOR: it plays no instrument itself. It creates the parts (window, engine, hotkey listener, menu bar icon, timer display) and
connects them. Read it in this order:

  1. THE FIRST HALF IS THE ENTRANCE:  make_parser (the options), main (read the settings, pick ONE job), then the small test modes
     keys_test / hotkey_test / toast_test / timer_test. Each test mode proves ONE thing in isolation (does macOS let us see keys? does the toast
     appear?). When something does not work on your Mac, run the matching test mode BEFORE guessing.
  2. run() IS THE REAL PROGRAM, in this order:
       a. take the "single instance" lock (myinstance): only one launcher may run; by default the NEWEST copy replaces the old ones.
       b. create the hidden Tk root and the LauncherWindow (mywindow), with an Engine (myengine) that talks to cli/.
       c. watch for shutdown (mypoweroff) and refuse to be closed by accident (protect_from_closing).
       d. start the hotkey listener (its own thread) and a WATCHDOG that restarts it if macOS switched it off.
       e. start the menu bar icon (its own thread too).
       f. start two repeating jobs with root.after: tick (every 1000 ms: timers) and poll (every 100 ms: the queue).
       g. root.mainloop(): hand control to Tk. Nothing below it runs until the program ends; everything after is clean-up.
  3. THE SAFETY NETS at the bottom: log_exit_calls and enable_stack_dumps make a program that silently dies or hangs leave EVIDENCE in the log.

THREADS, IN ONE PICTURE. A "thread" is a second line of execution inside one program. Three threads run here: the MAIN thread (Tk, the only one allowed to touch
the window), the HOTKEY thread (pynput waits for key events) and the MENU BAR thread (a Cocoa object). A thread must NEVER call window methods directly:
it only does `messages.put("toggle")`. A queue.Queue is safe to share between threads. The main thread empties it in `poll`. This is the whole trick.
`root.after(ms, function)` means "call this function in ms milliseconds, from the main loop". A function that ends with root.after(ms, itself) repeats forever
without a `while` loop that would freeze the window.
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
# sys.path is the list of folders Python searches when you write `import something`. insert(0, ...) puts a folder FIRST. Path(__file__).resolve().parent is the
# folder of this file (app/); .parent.parent is the project; / "cli" is the engine's folder. That is how app/ can `import myconfig` from cli/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cli"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# "noqa: E402" tells the style checker "yes, I know, these imports come after code (the sys.path lines): that is on purpose".
from myconfig import ConfigError, find_config_path, load_config  # noqa: E402
import mytimer  # noqa: E402
from myengine import Engine  # noqa: E402
from mymenubar import MenuBar  # noqa: E402
from myhotkey import HotkeyListener, describe, permission_report, watch_keys  # noqa: E402

POLL_MS = 100  # how often the main thread looks at the queue (10 times a second: you cannot feel the delay, and the cost is tiny)


def make_parser() -> argparse.ArgumentParser:
    """The command-line options. action="store_true" makes a switch: present = True, absent = False (--show, --keep-old...)."""
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

    # "Single instance": a lock file next to the usage file. acquire returns (lock, pid_of_the_other_copy); lock is None if somebody else holds it.
    # Two modes: --keep-old (the new copy leaves) or the default, the NEWEST copy stops the old ones and takes over (so "restart after an update" just works).
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

    # A SIGNAL is a message the operating system sends to a program (SIGTERM = "please end"). signal.signal(SIGTERM, function) says which function to call.
    # os._exit(0) leaves IMMEDIATELY, without clean-up: right when the Mac is shutting down, or `kill` is used. Exit code 0 = "finished normally".
    def quit_now(signum, frame):  # `kill`, a newer copy of the launcher, launchd at shutdown: leave at once and CLEANLY (exit 0: launchd does not restart it)
        print(f"[app] signal {signum}: leaving", flush=True)
        os._exit(0)

    signal.signal(signal.SIGTERM, quit_now)  # runs at the next 1-second tick at the latest
    print(f"python: {sys.executable}", flush=True)  # these lines go to the log file when started at login
    print_permissions()
    root = tk.Tk()
    root.withdraw()  # start hidden: the hotkey shows it
    # The window gets the root, the engine and the config; it never searches by itself (see myengine.py).
    window = LauncherWindow(root, Engine(config_path=config_path), config)
    import mypoweroff
    from mypower import already_asked

    # A one-item dict used as a box that nested functions can CHANGE (a plain variable assigned inside a nested function would create a new local one).
    leaving = {"now": False}

    def power_off_started() -> None:
        print("[app] the Mac is restarting / shutting down / logging out: leaving at once", flush=True)
        leaving["now"] = True
        os._exit(0)  # no clean-up needed, and nothing may delay the restart

    power_watch = mypoweroff.watch(power_off_started)  # keep the reference: the observer lives as long as this variable
    protect_from_closing(root, window, log=lambda text: print(text, flush=True),
                         may_quit=lambda: leaving["now"] or already_asked(config.power_lock))

    # THE MAILBOX between threads. The hotkey callback (hotkey thread) and the menu bar (its thread) put words in it: "toggle", "quit".
    # The lambda runs TWO expressions as a tuple, (print(...), messages.put("toggle")): print for the log, put for the real work.
    messages: queue.Queue = queue.Queue()
    listener = HotkeyListener(config.hotkey_modifiers, config.hotkey_key, lambda: (print("[hotkey] pressed", flush=True), messages.put("toggle")), swallow=config.hotkey_swallow)
    try:
        listener.start()
    except RuntimeError as exc:
        print(f"warning: no hotkey ({exc}); use --show", file=sys.stderr)
    else:
        print(f"hotkey swallowing: {'on' if listener.swallowing else 'off'}", flush=True)
        listener.guard(log=lambda text: print(text, flush=True))

    # try / except / else: `else` runs only if the try block raised NOTHING (here: the listener started, so announce it and guard it).
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

    # `bar = None` first, so later code can ask "if bar is not None" whether the icon exists.
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
    # A one-item list again used as a box (see `leaving`): tick remembers the last title it set, to call bar.set_title only when it CHANGED.
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
        root.after(1000, tick)  # re-arm AFTER the try/except: even after an error the next tick is scheduled

    root.after(1000, tick)

    def poll() -> None:
        # Empty the queue completely each time (while True ... break on Empty). get_nowait raises queue.Empty instead of waiting, so we never block.
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
    # root.mainloop() is where the program LIVES: Tk waits for events (keys, clicks, the `after` jobs) and calls our functions. It returns only after
    # root.quit() / destroy(). `finally` then stops the listener and the icon, whatever the reason we left.
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

    # root.protocol("WM_DELETE_WINDOW", f) replaces what the window's close button does; root.createcommand("::tk::mac::Quit", f) does the same for
    # the Apple "quit" event (Command+Q, or the Dock menu). Both are Tk features specific to how macOS talks to a Tk program.
    root.protocol("WM_DELETE_WINDOW", ignore_close)
    root.createcommand("::tk::mac::Quit", ignore_quit)


def log_exit_calls() -> None:
    """Print the Python stack whenever something calls sys.exit(): that names the culprit if it is Python code."""
    import traceback

    # An AUDIT HOOK is a function Python calls for sensitive events (opening files, exiting...). We only care about "sys.exit": print who called it.
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
        # faulthandler is in the standard library: on a crash or a signal it prints the Python stack of every thread. `kill -USR1 PID` = "show me where you are
        # right now" for a program that seems frozen. chain=True = print, then let the signal do its normal job (end the program).
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
    # A conditional expression: `A if condition else B`. The exit code of the chosen job is returned to the shell (0 = ok, non-zero = a problem).
    return hotkey_test(config) if args.hotkey_test else run(config, config_path, args.show, args.keep_old)


# Runs only when you start THIS file ("python3 app/mylauncher_app.py"), not when another file imports it (tests do). sys.exit(code) gives the code to the shell.
if __name__ == "__main__":
    sys.exit(main())
