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
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from myexecute import DEFAULT_SHELL, DEFAULT_SOURCE, DEFAULT_TERMINAL_COMMAND, background_script, terminal_script
import hashlib

import mynotify
import myaerospace
import mypower
import mytimer
import mynews
import myprayer
from mysecret import ensure_file
from mykill import alive, applescript_quote, running_apps
from mytypes import Item

# Actions that a "command" in the configuration file may use. (Apps always use open_app.)
COMMAND_ACTIONS = ("shutdown", "reboot", "screenshot_full", "screenshot_region", "weather", "briefing", "daily_gospel", "daily_gospel_image", "daily_gospel_post")


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
    notify_method: str = "auto"  # how: auto, osascript, terminal-notifier, none (see mynotify.py)
    copy_log: object = None  # copy_snippet: a file that gets one line per copy (None = no log)
    aerospace: bool = False  # open_app: switch to the workspace of the app first (see myaerospace.py)
    aerospace_command: str = "aerospace"
    aerospace_config: object = None  # the aerospace.toml with the [[on-window-detected]] rules
    aerospace_workspaces: tuple = ()  # (("Visual Studio Code", "C"), ...): your own choices, they win over the toml
    screenshot_dir: str = "auto"  # "auto" = where macOS saves screenshots (Desktop unless you changed it)
    screenshot_clipboard: bool = False  # copy to the clipboard instead of saving a file
    screenshot_delay: int = 1  # full screen: seconds to wait so the launcher window is gone
    power_force: bool = True  # reboot/shutdown: force quit the applications that refuse to quit (see mypower.py)
    power_grace: int = 8  # ... after this many seconds
    power_protected: tuple = ("python",)  # applications never touched: the launcher itself
    power_lock: object = None  # a marker file that stops a second request within 2 minutes (None = no guard)
    secret_notify_value: bool = True  # copy_secret: the notification shows the value
    timer_folder: str = "~/.config/mylauncher/timers"  # timer: one file per running timer
    timer_sound: str = "/System/Library/Sounds/Hero.aiff"  # timer
    timer_repeat: int = 4  # timer: how many times the sound plays
    timer_volume: float = 3.0  # timer: afplay gain (1 = as recorded)
    timer_speak: str = "Time is up"  # timer: said aloud at the end ("" = silent)
    timer_system_volume: int = 0  # timer: 0 = leave the Mac volume alone; 1-100 = set it for the ring, then restore
    weather_location: str = ""  # weather: "" = wttr.in guesses it from your address; or "Paris", "Madrid"...
    weather_format: str = "%c+%t"  # weather: wttr.in format (%c icon, %t temperature, %h humidity, %w wind...)
    weather_timeout: int = 6  # weather: seconds before giving up
    gospel_folder: str = ""  # daily_gospel: where the DATE-gospel-* files are
    gospel_image_count: int = 3
    news_feeds_file: str = ""  # news: conf/feeds.json
    news_cache_folder: str = "~/Library/Caches/mylauncher"
    news_timeout: int = 8
    clear_seconds: int = 30  # copy_secret: empty the clipboard again after this many seconds (0 = never)
    browser_command: tuple = ()  # open_url: ["/…/zen", "-new-tab", "{url}"]; empty = plain `open <url>`
    editor_command: tuple = ("open", "-a", "Visual Studio Code", "{path}")  # edit_file: {path} = the file
    shell: tuple = DEFAULT_SHELL  # execute_*: "<shell> <script>"
    source_files: tuple = DEFAULT_SOURCE  # execute_*: loaded before the command (your zsh functions)
    terminal_command: tuple = DEFAULT_TERMINAL_COMMAND  # execute_terminal: {command} = the script
    log_dir: Path = Path("~/Library/Logs/mylauncher/execute").expanduser()  # execute_background: one log per command
    execute_notify: bool = True  # execute_background: a notification when it ends
    spawn: object = field(default=None, repr=False)  # starts a program without waiting for it; None = default_spawn


def default_spawn(command: list, log_path) -> None:
    """Start a program and do NOT wait for it: a script may run for minutes, the launcher must not.

    Its output goes to `log_path` (replaced at every run: the log of the LAST run). start_new_session
    detaches it from the launcher, so it goes on even if the launcher is restarted.
    """
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "wb") as log:
        subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)  # noqa: S603


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
    """Open the application stored in item.target (after switching to its AeroSpace workspace, if that is set up)."""
    options = options or RunOptions()
    command = ["open", item.target]
    if not dry_run and not Path(item.target).exists():
        return ActionResult(False, f"{item.target} does not exist any more (moved or uninstalled?)", command)
    name = item.title.removeprefix("Run ")
    workspace, note = _aerospace_workspace(item, name, runner, dry_run, options)
    result = _execute(command, runner, dry_run, f"opened {name}" + (f" (AeroSpace workspace {workspace})" if workspace and not note else ""))
    if result.ok and note and not dry_run:
        result.message += f"  (AeroSpace: {note})"
    if dry_run and workspace:
        result.message += f"  and before it: aerospace workspace {workspace}"
    return result


def _aerospace_workspace(item, name: str, runner, dry_run: bool, options) -> tuple:
    """Switch AeroSpace to the workspace of the app. Returns (workspace, problem); ("", "") when there is nothing to do."""
    if not options.aerospace:
        return "", ""
    rules = []
    if options.aerospace_config:
        rules, _ = myaerospace.read_rules(options.aerospace_config)
    workspace = myaerospace.workspace_for(item.target, name, dict(options.aerospace_workspaces), rules)
    if not workspace:
        return "", ""
    program = myaerospace.find_command(options.aerospace_command)
    if not program:
        return workspace, f"the program '{options.aerospace_command}' was not found; the app opened without switching"
    if dry_run:
        return workspace, ""
    try:
        done = runner(myaerospace.switch_command(program, workspace))
    except OSError as exc:
        return workspace, f"could not run it ({exc})"
    if done.returncode != 0:
        detail = ((done.stderr or "").strip().splitlines() or [f"exit code {done.returncode}"])[-1]
        return workspace, f"could not switch to workspace {workspace}: {detail}"
    return workspace, ""


def _power(verb: str, doing: str, runner, dry_run: bool, options) -> ActionResult:
    """Restart ("restart") or shut down ("shut down") the Mac: see mypower.py for what happens and why."""
    options = options or RunOptions()
    final = ["osascript", "-e", f'tell application "System Events" to {verb}']
    if dry_run:
        extra = f" first close every application (force quit after {options.power_grace} s)," if options.power_force else ""
        return ActionResult(True, f"dry run, nothing was done. Would{extra} stop other launcher copies, then run: {shlex.join(final)}", final)
    apps, duplicates = mypower.plan(runner, options.power_protected, mypower.own_pids())
    if mypower.already_asked(options.power_lock):
        return ActionResult(False, f"{verb} was already requested less than {mypower.LOCK_SECONDS // 60} minutes ago; not asking twice", final)
    mypower.mark_asked(options.power_lock)
    if duplicates:
        runner(["kill", "-KILL", *map(str, duplicates)])  # a second copy would ask for the restart a second time
    if not options.power_force:
        return _execute(final, runner, False, f"{doing}...")
    script = mypower.power_script(apps, True, options.power_grace, final)
    command = ["/bin/sh", "-c", script]
    spawn = options.spawn or default_spawn
    try:
        spawn(command, Path(options.log_dir) / "power.log")
    except OSError as exc:
        return ActionResult(False, f"could not start the {verb} sequence: {exc}", command)
    return ActionResult(True, f"{doing}: closing {len(apps)} application(s), force quit after {options.power_grace} s...", command)


def shutdown(item: Item, runner=default_runner, dry_run: bool = False, options=None) -> ActionResult:
    """Shut down (like the Apple menu > Shut Down), also when an application refuses to quit."""
    return _power("shut down", "shutting down", runner, dry_run, options)


def reboot(item: Item, runner=default_runner, dry_run: bool = False, options=None) -> ActionResult:
    """Restart (like the Apple menu > Restart), also when an application refuses to quit."""
    return _power("restart", "restarting", runner, dry_run, options)


def _screenshot_folder(options, runner) -> str:
    """Where files go: the setting, or the place macOS itself uses (`defaults read com.apple.screencapture location`)."""
    if options.screenshot_dir and options.screenshot_dir != "auto":
        return str(Path(options.screenshot_dir).expanduser())
    try:
        done = runner(["defaults", "read", "com.apple.screencapture", "location"])
        if done.returncode == 0 and (done.stdout or "").strip():
            return str(Path((done.stdout or "").strip()).expanduser())
    except OSError:
        pass
    return str(Path("~/Desktop").expanduser())


def screenshot_script(region: bool, folder: str, clipboard: bool, delay: int, notify: bool, method: str) -> str:
    """The shell script that takes the picture (`screencapture`, a program of macOS) and says what happened."""
    flags = "-i -s" if region else f"-T {int(delay)}"  # region: the mouse chooses the area (Esc cancels); full: after `delay` s
    lines = [f"folder={shlex.quote(folder)}", 'name="Screenshot $(date \'+%Y-%m-%d at %H.%M.%S\').png"']
    if clipboard:
        lines += [f"screencapture -x -c {flags}", "code=$?", 'msg="copied to the clipboard"']
    else:
        lines += ['mkdir -p "$folder"', f'screencapture -x {flags} "$folder/$name"', "code=$?", 'msg="saved: $name"',
                  'if [ "$code" -eq 0 ] && [ ! -e "$folder/$name" ]; then code=1; msg="cancelled (no picture taken)"; fi']
    lines.append('if [ "$code" -ne 0 ] && [ "$msg" != "cancelled (no picture taken)" ]; then msg="failed (exit $code): is Screen Recording allowed for python?"; fi')
    if notify:
        lines.append(mynotify.script_line(method, "Screenshot"))
    lines.append('exit "$code"')
    return "\n".join(lines)


def _screenshot(region: bool, item: Item, runner, dry_run: bool, options) -> ActionResult:
    options = options or RunOptions()
    folder = _screenshot_folder(options, runner)
    script = screenshot_script(region, folder, options.screenshot_clipboard, options.screenshot_delay, options.notify, options.notify_method)
    command = ["/bin/sh", "-c", script]
    where = "the clipboard" if options.screenshot_clipboard else folder
    what = "drag to choose the area (Esc cancels)" if region else f"full screen in {options.screenshot_delay} s"
    if dry_run:
        return ActionResult(True, f"dry run, nothing was done. Would take a screenshot: {what} -> {where}", command)
    spawn = options.spawn or default_spawn  # not waited for: choosing an area takes as long as the user needs
    try:
        spawn(command, Path(options.log_dir) / "screenshot.log")
    except OSError as exc:
        return ActionResult(False, f"could not start screencapture: {exc}", command)
    return ActionResult(True, f"screenshot: {what} -> {where}", command)


def screenshot_full(item: Item, runner=default_runner, dry_run: bool = False, options=None) -> ActionResult:
    return _screenshot(False, item, runner, dry_run, options)


def screenshot_region(item: Item, runner=default_runner, dry_run: bool = False, options=None) -> ActionResult:
    return _screenshot(True, item, runner, dry_run, options)


def weather_url(location: str, fmt: str) -> str:
    """https://wttr.in/Paris?format=%c+%t  (the location may be empty; spaces become +)."""
    return "https://wttr.in/" + urllib.parse.quote(location.strip().replace(" ", "+"), safe="+,~") + "?format=" + fmt


def weather(item: Item, runner=default_runner, dry_run: bool = False, options=None) -> ActionResult:
    """The same as  curl -s "wttr.in/?format=%c+%t"  : one line with the weather, shown in a notification."""
    options = options or RunOptions()
    command = ["curl", "-s", "-f", "--max-time", str(int(options.weather_timeout)), weather_url(options.weather_location, options.weather_format)]
    if dry_run:
        return ActionResult(True, "dry run, nothing was done. Would ask wttr.in: " + " ".join(command), command)
    try:
        done = runner(command)
    except FileNotFoundError:
        return ActionResult(False, "the program 'curl' was not found", command)
    text = " ".join((done.stdout or "").split())
    if done.returncode != 0 or not text or text.lower().startswith(("unknown location", "<")):
        return ActionResult(False, f"no weather (curl exit code {done.returncode}): is the Mac online? {text[:60]}".strip(), command)
    if options.notify:
        place = options.weather_location.strip() or "here"
        ok, detail = mynotify.send(runner, options.notify_method, "mylauncher", f"Weather ({place})", text)
        if not ok:
            text += f"  (notification failed: {detail})"
    return ActionResult(True, text, command)


def news_refresh(item: Item, runner=default_runner, dry_run: bool = False, options=None, fetcher=None) -> ActionResult:
    """Row "Refresh <category> news" (item.target = the category): fetch every feed of it now and fill the cache."""
    options = options or RunOptions()
    if dry_run:
        return ActionResult(True, f"dry run, nothing was done. Would fetch the {item.target} feeds from {options.news_feeds_file}", [])
    try:
        categories = mynews.load_feeds(Path(options.news_feeds_file))
        result = mynews.refresh(categories, item.target, options.news_cache_folder, options.news_timeout, fetcher or mynews.default_fetcher)
    except mynews.NewsError as error:
        return ActionResult(False, str(error), [])
    if not result["entries"]:
        return ActionResult(False, f"no headlines for {item.target!r}: is the Mac online? ({len(result['failed'])} feed(s) failed)", [])
    total, bad = len(result["entries"]), len(result["failed"])
    return ActionResult(True, f"{total} headlines for {item.target!r}" + (f"  ({bad} feed(s) did not answer)" if bad else "") + ".", [])


def ml_command(*words) -> str:
    """The shell line that runs `ml <words>` in a terminal. bash runs the script: no executable bit needed."""
    return shlex.join(["/bin/bash", str(Path(__file__).resolve().parent / "ml"), *words])


def briefing(item: Item, runner=default_runner, dry_run: bool = False, options=None) -> ActionResult:
    """`daily briefing` (a command row): open a terminal that runs  ml daily-briefing."""
    return execute_terminal(Item(id=item.id, title="daily briefing", kind="ai", action="execute_terminal", target=ml_command("daily-briefing")), runner, dry_run, options)


def daily_gospel(item: Item, runner=default_runner, dry_run: bool = False, options=None) -> ActionResult:
    """`daily_gospel` (a command row). If today's prayer and pictures are already made, open the page (DATE-gospel-prayer.html) in the
    browser at once. Otherwise open a terminal that runs  ml daily-gospel  (it makes everything, then opens the page itself)."""
    options = options or RunOptions()
    folder = Path(options.gospel_folder).expanduser() if options.gospel_folder else None
    day = time.strftime("%Y-%m-%d")
    data = myprayer.load_day(folder, day) if folder else None
    if data and myprayer.prayer_done(data) and myprayer.images_done(data, folder, options.gospel_image_count):
        files = myprayer.day_files(folder, day)
        if dry_run:
            return ActionResult(True, f"dry run, nothing was done. Would open {files['html']}", [])
        if not files["html"].exists():  # made by an older version: draw the page from the saved data
            files["html"].write_text(myprayer.render_html(data, data.get("title", "Daily Gospel")), encoding="utf-8")
        if myprayer.open_page(files["html"], options.browser_command, runner):
            return ActionResult(True, f"today's prayer ({files['html'].name}) is open in your browser", [])
        return ActionResult(False, f"could not open {files['html']}", [])
    return execute_terminal(Item(id=item.id, title="daily gospel", kind="ai", action="execute_terminal", target=ml_command("daily-gospel")), runner, dry_run, options)


def daily_gospel_image(item: Item, runner=default_runner, dry_run: bool = False, options=None) -> ActionResult:
    """`daily_gospel_image` (a command row): open a terminal that runs  ml daily-gospel-image (a prompt, then three pictures)."""
    return execute_terminal(Item(id=item.id, title="daily gospel image", kind="ai", action="execute_terminal", target=ml_command("daily-gospel-image")), runner, dry_run, options)


def daily_gospel_post(item: Item, runner=default_runner, dry_run: bool = False, options=None) -> ActionResult:
    """`daily_gospel_post` (a command row, with confirmation: it PUBLISHES): a terminal that runs  ml daily-gospel-post."""
    return execute_terminal(Item(id=item.id, title="daily gospel post", kind="ai", action="execute_terminal", target=ml_command("daily-gospel-post")), runner, dry_run, options)


def timer(item: Item, runner=default_runner, dry_run: bool = False, options=None) -> ActionResult:
    """Start a timer in the background (item.target = seconds): when it ends, a notification and a sound.

    A small file in `timer.folder` says "this timer is running": the window and the menu bar count down from it,
    and the script stops quietly when the file is deleted (that is how a timer is cancelled).
    """
    options = options or RunOptions()
    seconds = int(item.target)
    ends = time.strftime("%H:%M:%S", time.localtime(time.time() + seconds))
    if dry_run:
        return ActionResult(True, f"dry run, nothing was done. Would start a timer of {mytimer.format_duration(seconds)}", [])
    try:
        state = mytimer.start_file(options.timer_folder, seconds, time.time())
        script = mytimer.timer_script(seconds, options.notify_method, options.timer_sound, options.timer_repeat, state_file=str(state), volume=options.timer_volume, speak=options.timer_speak, system_volume=options.timer_system_volume)
        command = [*options.shell, script]
        (options.spawn or default_spawn)(command, Path(options.log_dir) / "timer.log")
    except OSError as exc:
        return ActionResult(False, f"could not start the timer: {exc}", [])
    return ActionResult(True, f"timer of {mytimer.format_duration(seconds)} started: it rings at {ends}", command)


def timer_cancel(item: Item, runner=default_runner, dry_run: bool = False, options=None) -> ActionResult:
    """Cancel a running timer (item.target = its id)."""
    options = options or RunOptions()
    if dry_run:
        return ActionResult(True, "dry run, nothing was done", [])
    done = mytimer.cancel(options.timer_folder, item.target)
    return ActionResult(True, "timer cancelled" if done else "that timer had already ended", [])


def open_url(item: Item, runner=default_runner, dry_run: bool = False, options=None) -> ActionResult:
    """Open the web address stored in item.target.

    With `browser.command` in the configuration (for Zen/Firefox:  zen -new-tab {url} ) the address
    opens as a NEW TAB of the browser that is already running; a plain `open <url>` can start a second
    instance (a new window) instead. If that command is missing or fails, we fall back to `open`, so a
    typing mistake in the setting never leaves you without your search.
    """
    options = options or RunOptions()
    fallback = ["open", item.target]
    if not item.target.startswith(("http://", "https://")):  # never hand anything else to `open`
        return ActionResult(False, f"refusing to open {item.target!r}: only http:// and https:// addresses", fallback)
    if not options.browser_command:
        return _execute(fallback, runner, dry_run, f"opened {item.target}")
    command = [part.replace("{url}", item.target) for part in options.browser_command]
    if dry_run:
        return _execute(command, runner, dry_run, "")
    try:
        completed = runner(command)
        worked = completed.returncode == 0
    except FileNotFoundError:
        worked = False
    if worked:
        return ActionResult(True, f"opened {item.target} in a new tab", command)
    result = _execute(fallback, runner, dry_run, f"opened {item.target} (the browser command did not work: {shlex.join(command[:1])})")
    return result


def prefix_hint(item: Item, runner=default_runner, dry_run: bool = False, options=None) -> ActionResult:
    """Items like "yt" or "kill" need text after them; pressing Enter on them only explains that."""
    return ActionResult(False, f"type something after it, for example:  {item.complete}...", [])


NOTIFICATION_WIDTH = 120  # a notification shows only a few lines: cut long texts


def _clipboard_holds(runner, text: str) -> bool:
    """Read the clipboard back (`pbpaste`) and compare: an honest "it worked", not a hope."""
    try:
        done = runner(["pbpaste"])
    except Exception:  # noqa: BLE001 - cannot check: do not fail a copy that probably worked
        return True
    return done.returncode != 0 or (done.stdout or "").replace("\r\n", "\n") == text.replace("\r\n", "\n")


def _log_copy(path, item, count: int, checked: bool, seconds: float) -> None:
    if not path:
        return
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as log:
            log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {item.id}  {count} chars  clipboard {'verified' if checked else 'DIFFERENT'}  {seconds * 1000:.0f} ms\n")
    except OSError:
        pass  # a log must never break a copy


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
    started = time.monotonic()
    checked = _clipboard_holds(runner, item.target)
    if not checked:  # the clipboard does not hold the text: try once more
        runner(command, input_text=item.target)
        checked = _clipboard_holds(runner, item.target)
    _log_copy(options.copy_log, item, count, checked, time.monotonic() - started)
    message = f"{item.title} copied to the clipboard ({count} characters)"
    if not checked:
        return ActionResult(False, f"{item.title}: pbcopy ran but the clipboard does not hold the {count} characters (see {options.copy_log or 'ml doctor'})", command)
    if options.notify:
        shown = item.subtitle[:NOTIFICATION_WIDTH] or item.target[:NOTIFICATION_WIDTH]
        ok, detail = mynotify.send(runner, options.notify_method, "mylauncher", f"{item.title} copied to the clipboard", shown)
        if not ok:
            message += f"  (notification failed: {detail}; try: ml notify-test)"
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
def copy_secret(item: Item, runner=default_runner, dry_run: bool = False, options=None) -> ActionResult:
    """Copy a secret value to the clipboard and empty the clipboard again after `clear_seconds`.

    The value is never printed or logged. To empty the clipboard only if it STILL holds the secret (you may
    have copied something else since), a background shell compares a SHA-256 fingerprint of the clipboard
    with the secret's; the fingerprint is one-way, the secret itself is never on a command line.
    """
    options = options or RunOptions()
    command = ["pbcopy"]
    if dry_run:
        return ActionResult(True, f"dry run, nothing was done. Would copy {item.title} with pbcopy and empty the clipboard after {options.clear_seconds} s", command)
    try:
        done = runner(command, input_text=item.target)
    except FileNotFoundError:
        return ActionResult(False, "the program 'pbcopy' was not found (is this a Mac?)", command)
    if done.returncode != 0:
        return ActionResult(False, f"could not copy: {(done.stderr or '').strip() or f'exit code {done.returncode}'}", command)
    message = f"{item.title} copied to the clipboard"
    if options.clear_seconds > 0:
        fingerprint = hashlib.sha256(item.target.encode("utf-8")).hexdigest()
        script = f'sleep {int(options.clear_seconds)}; [ "$(pbpaste | /usr/bin/shasum -a 256)" = "{fingerprint}  -" ] && printf "" | pbcopy'
        try:
            (options.spawn or default_spawn)(["/bin/sh", "-c", script], Path(options.log_dir) / "secret-clear.log")
            message += f" (the clipboard is emptied in {options.clear_seconds} s)"
        except OSError:
            message += " (could not schedule emptying the clipboard)"
    if options.notify:
        shown = item.target if options.secret_notify_value else ""
        if shown and item.id == "secret:*all*":
            shown = ""  # the "all" table is too long for a notification
        tail = f"(clipboard emptied in {options.clear_seconds} s)" if options.clear_seconds else ""
        body = (shown.splitlines()[0] if shown else "") or tail
        ok, detail = mynotify.send(runner, options.notify_method, "mylauncher", f"{item.title} copied", body)
        if not ok:
            message += f"  (notification failed: {detail})"
    return ActionResult(True, message, command)


def edit_secret(item: Item, runner=default_runner, dry_run: bool = False, options=None) -> ActionResult:
    """Open the secret file in the editor; create it first (permissions 600) if it does not exist."""
    options = options or RunOptions()
    if dry_run:
        return edit_file(item, runner, True, options)
    try:
        path, done = ensure_file(item.target)
    except OSError as exc:
        return ActionResult(False, f"cannot create {item.target}: {exc}", [])
    result = edit_file(Item(item.id, item.title, "edit", "edit_file", target=str(path)), runner, False, options)
    if result.ok and done:
        result = ActionResult(True, f"{result.message} ({done})", result.command)
    return result


def edit_file(item: Item, runner=default_runner, dry_run: bool = False, options=None) -> ActionResult:
    """Open item.target in the editor of the configuration (`edit.editor`).

    If that editor cannot be started (the application is not installed, a typing mistake...) we fall
    back to `open -t`: the editor macOS uses for text files. The file must exist.
    """
    options = options or RunOptions()
    path = Path(item.target)
    command = [part.replace("{path}", str(path)) for part in options.editor_command]
    fallback = ["open", "-t", str(path)]
    if dry_run:
        return ActionResult(True, f"dry run, nothing was done. Would run: {shlex.join(command)}", command)
    if not path.exists():
        return ActionResult(False, f"file not found: {path}", command)
    try:
        done = runner(command)
        worked = done.returncode == 0
    except FileNotFoundError:
        worked = False
    if worked:
        return ActionResult(True, f"opened {path}", command)
    result = _execute(fallback, runner, False, f"opened {path} (the editor command did not work: {shlex.join(command[:3])})")
    return result


def _log_path(item: Item, options: RunOptions) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in item.title) or "command"
    return Path(options.log_dir) / f"{safe}.log"


def execute_background(item: Item, runner=default_runner, dry_run: bool = False, options=None) -> ActionResult:
    """Run item.target (a command line) in the background: zsh starts it and we do not wait.

    A notification tells how it ended; its output is in the log file (shown in the message).
    """
    options = options or RunOptions()
    script = background_script(item.title, item.target, options.source_files, options.execute_notify, options.notify_method)
    command = [*options.shell, script]
    log = _log_path(item, options)
    if dry_run:
        return ActionResult(True, f"dry run, nothing was done. Would run in the background: {item.target}   (zsh script and log: {log})", command)
    spawn = options.spawn or default_spawn
    try:
        spawn(command, log)
    except OSError as exc:
        return ActionResult(False, f"could not start {item.title!r}: {exc}", command)
    return ActionResult(True, f"started {item.title!r} in the background (log: {log})", command)


def execute_terminal(item: Item, runner=default_runner, dry_run: bool = False, options=None) -> ActionResult:
    """Run item.target in a new terminal window (`execute.terminal_command`), so you see the output.

    If the terminal cannot be started, run it in the background instead, so the command is not lost.
    """
    options = options or RunOptions()
    script = terminal_script(item.target, options.source_files)
    command = [part.replace("{command}", script) for part in options.terminal_command]
    if dry_run:
        return ActionResult(True, f"dry run, nothing was done. Would run in a terminal: {item.target}   (command: {shlex.join(command[:4])} ...)", command)
    try:
        done = runner(command)
        worked = done.returncode == 0
    except FileNotFoundError:
        worked = False
    if worked:
        return ActionResult(True, f"started {item.title!r} in a terminal window", command)
    result = execute_background(item, runner, False, options)
    if result.ok:
        return ActionResult(True, f"{result.message}  (the terminal command did not work: {shlex.join(command[:3])})", result.command)
    return result


ACTIONS = {
    "copy_secret": copy_secret,
    "edit_secret": edit_secret,
    "edit_file": edit_file,
    "execute_background": execute_background,
    "execute_terminal": execute_terminal,
    "open_app": open_app,
    "shutdown": shutdown,
    "reboot": reboot,
    "weather": weather,
    "timer": timer,
    "timer_cancel": timer_cancel,
    "briefing": briefing,
    "daily_gospel": daily_gospel,
    "daily_gospel_image": daily_gospel_image,
    "daily_gospel_post": daily_gospel_post,
    "news_refresh": news_refresh,
    "screenshot_full": screenshot_full,
    "screenshot_region": screenshot_region,
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
