"""
mywindow.py - the window, drawn with tkinter (Python's standard graphical library).

What you see: a dark rounded window (no title bar buttons: see mychrome.py) with a text box, where the
word the launcher recognised (kill, yt, ;p ...) is painted in colour, and under it the list of rows: an
emoji, the title, some grey information and a small label saying what the row is.
What the keys do:
    typing        new suggestions (lowercase or UPPERCASE, it is the same)
    Up / Down     move the selection (wraps around)
    Tab           autocomplete: writes the first suggestion in the text box
    Enter         do the selected item (Shutdown asks "are you sure?" first). On a hint such as
                  "yt" or "kill" Enter does what Tab does: writes "yt " and waits for your text.
    Escape        hide the window

Rules of this file:
  * No decisions about search or actions: the engine (cli/) does them, through myengine.py.
  * The selection logic is in mystate.py. Here we only DRAW and pass key presses along.
  * Only the main thread may touch tkinter. The hotkey arrives in another thread, so it only puts a
    message in a queue (see mylauncher_app.py); the main thread picks it up.

`root` is the tkinter main window and `engine`/`config` are given from outside, so tests can pass fakes.

GUIDED TOUR (for someone who is just starting to program) ---------------------------------------------------------------
This is the biggest file of app/, but it has only ONE class and the methods fall into five groups. Read them in this order:
  1. TWO HELPER FUNCTIONS    press_command_v, bring_to_front        talk to macOS (Quartz key events; AppleScript "System Events").
  2. CONSTANTS               TOAST_KINDS, SHOW_RESULT_IDS, HINT, DETAIL_HINT     the policy "after which rows do we say something".
  3. __init__ AND _build     create the widgets once and bind the keys.
  4. SHOW / HIDE             show, _resize, hide, toggle.
  5. REACTING                refresh (the heart), tick, _move, _autocomplete, _clicked, _open_detail/_close_detail, _run_selected (the longest method).

THE LOOP THAT IS THE WHOLE PROGRAM. type a letter -> CommandInput calls on_change -> refresh() -> engine.search(text) -> state.set_answer(json) -> _draw_list().
Press Enter -> _run_selected() -> engine.run(id, text) -> look at the ActionResult -> hide, toast, paste, or stay open. Everything else is detail.

TKINTER IN FIVE LINES. A tkinter program is a tree of WIDGETS (Frame, Label, Text...). You create one with its parent: tk.Label(parent, text="hi"). It does not appear
until you PLACE it: .pack() stacks it (side="left"/"right" glues it to a side, fill="x" stretches it, padx/pady add space). .pack_forget() removes it again. EVENTS:
widget.bind("<Return>", function) calls the function when the key is pressed, and if the function returns the string "break" tkinter stops there and does NOT
run its default behaviour (without that, Return would insert a new line and Tab would jump to another widget). Nothing is drawn until the main loop runs.

RULE OF THE LAUNCHER WINDOW: the UI NEVER DIES. Notice the many `try/except Exception` that put the problem in the status line instead of crashing: a launcher that
vanishes when one search fails is worse than one that says "error: ...".
"""

from __future__ import annotations

import os
import subprocess
import time
import tkinter as tk
from tkinter import messagebox

from mychrome import default_style
from mystate import LauncherState
from mytheme import make_theme, mode_label
from mytoast import Toast
from mywidgets import CommandInput, DetailView, ResultList


# Quartz is macOS's low-level graphics/event library (via PyObjC). A "key code" is the number of a PHYSICAL key (9 is the V key, whatever the layout), not a letter.
# We send two events, key down then key up (`for down in (True, False)`), with the Command modifier "flag" set: that is Command+V. The comment says why we do
# not use pynput here: it can crash Python when used from this thread.
def press_command_v() -> None:
    """Type Command+V into whatever application is in front, with Quartz (no pynput: it can crash Python)."""
    import Quartz

    V = 9  # the key code of the "v" key
    for down in (True, False):
        event = Quartz.CGEventCreateKeyboardEvent(None, V, down)
        Quartz.CGEventSetFlags(event, Quartz.kCGEventFlagMaskCommand)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


def bring_to_front(runner=subprocess.run, pid: int | None = None) -> None:
    """Ask macOS to make THIS program the active one.

    A program started from Terminal is not "in front" when its window appears, so typing would go to
    the previous application. This is the usual trick: ask System Events to put our process in front.
    If it fails, nothing breaks (we only lose the keyboard focus), so errors are ignored.
    """
    # os.getpid() = the number the operating system gave THIS running program (its "process id"). AppleScript is run with `osascript -e SCRIPT`. The f-string
    # puts the pid inside the script text. `pid is None` (not `not pid`) because 0 would be a legitimate value to pass in a test.
    pid = os.getpid() if pid is None else pid
    script = f'tell application "System Events" to set frontmost of the first process whose unix id is {pid} to true'
    try:
        runner(["osascript", "-e", script], capture_output=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass  # not on a Mac, or too slow: fine


# After these kinds of rows the window says what happened (a copy, a started command...); opening an app needs no message.
# These tuples are POLICY as data: to change which rows show a toast you edit a list, not an if-chain. (The `kind` is a field of every result row.)
TOAST_KINDS = ("snippet", "help", "secret", "execute", "edit", "kill", "emoji", "emoji_fav")
SHOW_RESULT_IDS = ("cmd:weather",)  # after these the answer stays on screen (like a help row) instead of closing the window
HINT = "↩ open     ⇥ complete     ⎋ close"
DETAIL_HINT = "↩ copy     ↑ ↓ scroll     ⎋ back to the list"


class LauncherWindow:
    """The window. Everything that touches the Mac or the user is a PARAMETER with a real default: `front` (bring to front), `confirm` (the yes/no dialog),
    `style` (mychrome), `paste` (Command+V). Tests pass fakes for all four, so the whole window logic runs without a screen's help and without ever asking a human."""

    def __init__(self, root: tk.Tk, engine, config, front=bring_to_front, confirm=messagebox.askyesno, style=default_style, paste=press_command_v):
        self.root, self.engine, self.config = root, engine, config
        self.front, self.confirm, self.style, self.paste = front, confirm, style, paste
        self.theme = make_theme(config)
        self.state = LauncherState(rows=config.max_results)
        self.visible = False
        self.styled = False
        # `X if condition else None`: with the toast switched off in the settings, self.toast is None and later code asks `if self.toast and ...`.
        self.toast = Toast(root, self.theme, config.toast_seconds, config.window_top_offset) if config.toast else None
        self.detail_item = None  # the help row whose full text is on screen (None = the list is shown)
        self._position = (0, config.window_top_offset)
        self._build()

    # ---- building the widgets -------------------------------------------- #

    def _build(self) -> None:
        root, config, t = self.root, self.config, self.theme
        root.title(config.window_title)
        root.resizable(False, False)
        root.configure(bg=t.background)
        # An ESTIMATE: a character is roughly 0.55 times the font size wide, so width / (size * 0.55) is about how many fit. It only decides where
        # row_texts cuts the subtitle (mytheme.py); a rough number is enough, an exact one would need measuring every font.
        characters = int(config.window_width / (t.row_size * 0.55))  # about how many characters fit in a row

        # The "search bar": the text box (left) and the mode label (right) share one background.
        bar = tk.Frame(root, bg=t.input_background)
        bar.pack(fill="x", padx=14, pady=(8, 8))
        self.mode = tk.Label(bar, text="", bg=t.input_background, fg=t.muted, font=(t.font, t.small_size), padx=10)
        self.mode.pack(side="right")
        # on_change is a CALLBACK: "call this when the text changes". The lambda ignores the text it receives (_text) because refresh() reads it again itself.
        self.input = CommandInput(bar, t, on_change=lambda _text: self.refresh())
        self.input.text.pack(side="left", fill="x", expand=True)

        self.list = ResultList(root, t, rows=config.max_results, characters=characters, on_click=self._clicked)
        self.list.frame.pack(fill="x", padx=14)

        # DetailView is created but NOT packed: invisible until _open_detail swaps it in for the list. Creating once and showing/hiding is cheaper and avoids flicker.
        self.detail = DetailView(root, t)  # not packed: it replaces the list while a help row is open

        self.status = tk.Label(root, text=HINT, anchor="w", bg=t.background, fg=t.muted, font=(t.font, t.small_size))
        self.status.pack(fill="x", padx=18, pady=(6, 10))

        # Keys. Returning "break" tells tkinter: "I handled it, do not do your normal thing".
        text = self.input.text
        text.bind("<Down>", lambda e: self._move(+1))
        text.bind("<Up>", lambda e: self._move(-1))
        text.bind("<Tab>", lambda e: self._autocomplete())
        text.bind("<Return>", lambda e: self._run_selected())
        root.bind("<Escape>", lambda e: self._escape())

    # ---- showing and hiding ---------------------------------------------- #

    def show(self) -> None:
        """Order matters here, and each line has a reason: empty the box and fill the list; compute the centre (screen width minus window width, halved:
        `//` is integer division, a pixel position cannot be a fraction); size; deiconify (un-hide); topmost + lift (above everything); style ONCE after the real
        Cocoa window exists (hence root.update()); bring the program to the front so the KEYBOARD comes to us; focus the text box."""
        self.input.set("")
        self.refresh()
        self.root.update_idletasks()
        width = self.config.window_width
        self._position = ((self.root.winfo_screenwidth() - width) // 2, self.config.window_top_offset)
        self._resize()
        self.root.deiconify()
        self.root.attributes("-topmost", True)  # above the other windows
        self.root.lift()
        if not self.styled and self.config.window_style == "borderless":
            self.root.update()  # the real (Cocoa) window must exist before we can style it
            self.styled = bool(self.style(self.config.window_title, self.theme.background))
        self.front()
        self.input.focus()
        self.visible = True

    def _resize(self) -> None:
        """The window is as tall as its rows: few results, small window."""
        self.root.update_idletasks()
        x, y = self._position
        # A tkinter geometry string is "WIDTHxHEIGHT+X+Y". winfo_reqheight is the height the widgets ASK for: few rows, short window; no scroll bars to manage.
        self.root.geometry(f"{self.config.window_width}x{self.root.winfo_reqheight()}+{x}+{y}")

    def hide(self) -> None:
        self._close_detail()
        self.root.withdraw()
        self.visible = False

    def toggle(self) -> None:
        self.hide() if self.visible else self.show()  # one-line "if": call hide() when visible, else show(). (Used as a statement, for its effect.)

    # ---- reacting to the user -------------------------------------------- #

    def refresh(self) -> None:
        """Ask the engine for suggestions for the current text and draw them."""
        # Two separate try/except blocks on purpose: the FIRST protects "ask the engine" (it can fail: engine missing, bad JSON); the SECOND protects "draw"
        # (it can fail: a result with an unexpected field). Each failure puts a different sentence in the status line, so you know which half broke.
        typed = self.input.get()
        self._close_detail()  # typing again means "back to the list"
        try:
            self.state.set_answer(self.engine.search(typed))
            self.status.config(text=HINT)
        except Exception as exc:  # the window must never die: show the problem instead
            self.state.clear()
            self.status.config(text=f"error: {exc}")
        try:
            # highlight is how many leading characters the ENGINE recognised as the command ("yt" in "yt lofi"); min(..., len(typed)) guards against an answer
            # that arrives after you deleted letters (the answer is slightly old, the text is newer).
            self.input.paint_command(min(self.state.highlight, len(typed)))
            self.mode.config(text=mode_label(self.state.mode))
            self._draw_list()
        except Exception as exc:  # drawing must never fail silently: say it in the window and in the log
            import traceback

            traceback.print_exc()
            self.status.config(text=f"error drawing {len(self.state.results)} row(s): {exc}")
        if self.visible:
            self._resize()

    def tick(self, now=None) -> None:
        """Once a second (the application calls it): the rows of the running timers count down: 00:02:59, 00:02:58 ..."""
        if not self.visible or self.detail_item is not None:
            return
        # A running-timer row stores its END TIME (a timestamp) in "detail". Each second we subtract `now` to get the remaining seconds and rewrite the title.
        # No engine call per second: the window does the arithmetic itself, and asks the engine again only when a timer has expired (remaining < -1).
        rows = [r for r in self.state.results if r.get("kind") == "timer_run"]
        if not rows:
            return
        from mytimer import clock

        now = time.time() if now is None else now
        expired = False
        for row in rows:
            remaining = float(row["detail"]) - now
            row["title"] = clock(remaining)
            expired = expired or remaining < -1  # it rang: ask the engine again, the row disappears
        self._draw_list()
        if expired:
            self.refresh()

    def _draw_list(self) -> None:
        self.list.draw(self.state.visible, self.state.visible_selected)

    def _escape(self) -> None:
        """Esc: from the full text back to the list; from the list, hide the window."""
        if self.detail_item is not None:
            self._close_detail()
        else:
            self.hide()

    def _open_detail(self, item: dict) -> None:
        self.detail_item = item
        self.detail.show(f"{item['icon']}  {item['title']}", item["detail"])
        self.list.frame.pack_forget()
        # `before=self.status` puts the frame ABOVE the status line in the stacking order: otherwise pack would add it at the very bottom, under the hint.
        self.detail.frame.pack(fill="x", padx=14, before=self.status)
        self.status.config(text=DETAIL_HINT)
        self._resize()

    def _close_detail(self) -> None:
        if self.detail_item is None:
            return
        self.detail_item = None
        self.detail.frame.pack_forget()
        self.list.frame.pack(fill="x", padx=14, before=self.status)
        self.status.config(text=HINT)
        self._resize()

    def _move(self, step: int) -> str:
        # `step * 3`: three lines per key press. Returning "break" (here and below) stops tkinter's own handling of the arrow keys in the text box.
        if self.detail_item is not None:  # the arrows scroll the text instead of moving in the list
            self.detail.scroll(step * 3)
            return "break"
        self.state.move(step)
        self._draw_list()  # scrolling changes which rows are shown, so draw them again
        return "break"

    def _clicked(self, row: int) -> None:
        self.state.select_visible(row)
        self._draw_list()
        self._run_selected()

    def _autocomplete(self) -> str:
        wanted = self.state.tab_text(self.input.get())
        if wanted != self.input.get():
            self.input.set(wanted)
        return "break"  # without this, Tab would jump to another widget

    def _paste(self) -> None:
        """The text is on the clipboard and the window is gone: press Command+V where the user was typing."""
        try:
            self.paste()
            print("[run] pasted (Command+V)", flush=True)
        except Exception as exc:  # noqa: BLE001 - a failed paste leaves the text on the clipboard: say so, do not crash
            print(f"[run] could not paste ({type(exc).__name__}: {exc}); the text is on the clipboard", flush=True)

    def _run_selected(self) -> str:
        """What Enter (or a click) does. A DECISION LIST, top to bottom; the first rule that applies returns "break" and the rest is skipped:
          1. no item -> nothing.   2. the weather answer on screen -> close.   3. help/secret rows -> FIRST Enter opens the full text, the NEXT Enter copies
          (a named secret copies at once: `one_enter`).   4. a "prefix" hint -> write it into the box and wait for your words.   5. needs confirmation ->
          ask yes/no.   6. ask the engine to RUN it; if an app would not quit offer force quit.   7. what to do with the answer: timers and news stay open,
          the weather result opens the detail view, success hides the window and maybe pastes and toasts, failure shows the error in the status line.
        Every `print("[run] ...")` writes to the log, so when something "does nothing" you can see how far the action got."""
        item = self.detail_item if self.detail_item is not None else self.state.current
        if item is None:
            return "break"
        if item["kind"] == "result":  # the answer of weather: Enter closes it
            self.hide()
            return "break"
        one_enter = item["kind"] == "secret" and item["id"] not in ("secret:*all*", "secret:*vault*")  # a named secret: ONE Enter copies it
        if item["kind"] in ("help", "secret") and self.detail_item is None and item.get("detail") and not one_enter:
            self._open_detail(item)  # first Enter: read it; the next Enter copies it (below)
            return "break"
        if item["kind"] == "prefix":  # a hint ("yt", "kill", ";p"): there is nothing to run yet, so write it and wait
            self.input.set(item["complete"])
            return "break"
        if item["confirm"] and not self.confirm(self.config.window_title, f"{item['title']}: are you sure?", parent=self.root):
            return "break"
        typed = self.input.get()
        print(f"[run] {item['id']} ...", flush=True)  # the log shows how far an action got
        result = self.engine.run(item["id"], typed)
        print(f"[run] {item['id']} -> {'ok' if result.ok else 'error'}: {result.message[:80]}", flush=True)
        if result.needs_force:  # an app did not quit: only force quit if the user agrees
            question = f"{result.message}\n\nForce quit now?"
            if self.confirm(self.config.window_title, question, parent=self.root):
                result = self.engine.run(item["id"], typed, force=True)
        if result.ok and item["kind"] in ("timer", "timer_run"):  # stay open: the countdown is the answer
            self.input.set("timer ")
            self.refresh()
            self.status.config(text=f"✔  {result.message}")
            print("[run] timers shown", flush=True)
            return "break"
        if result.ok and item.get("kind") == "news_refresh":  # stay open and show the headlines that were just fetched
            self.input.set(item.get("complete") or "news ")
            self.refresh()
            self.status.config(text=f"✔  {result.message}")
            print("[run] news shown", flush=True)
            return "break"
        if result.ok and item["id"] in SHOW_RESULT_IDS and result.message:
            self._open_detail({"id": "result", "kind": "result", "icon": item.get("icon", ""), "title": item["title"], "detail": result.message, "confirm": False})
            self.status.config(text="↩ or ⎋ close")
            print("[run] result shown in the window", flush=True)
            return "break"
        # Success: hide first (the keyboard goes back to the app you were in), THEN paste after a short delay (root.after) so that app is really in front again.
        if result.ok:
            self.hide()
            print("[run] window hidden", flush=True)
            if (item["kind"] == "snippet" and self.config.expander_paste) or (item["kind"] == "emoji" and self.config.emoji_paste):
                self.root.after(self.config.expander_paste_delay_ms, self._paste)
            if self.toast and item["kind"] in TOAST_KINDS and result.message:
                self.toast.show(f"✔  {result.message}")
                print("[run] toast shown", flush=True)
        else:
            self.status.config(text=f"error: {result.message}")
        return "break"
