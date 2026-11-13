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
"""

from __future__ import annotations

import os
import subprocess
import tkinter as tk
from tkinter import messagebox

from mychrome import default_style
from mystate import LauncherState
from mytheme import make_theme, mode_label
from mywidgets import CommandInput, ResultList


def bring_to_front(runner=subprocess.run, pid: int | None = None) -> None:
    """Ask macOS to make THIS program the active one.

    A program started from Terminal is not "in front" when its window appears, so typing would go to
    the previous application. This is the usual trick: ask System Events to put our process in front.
    If it fails, nothing breaks (we only lose the keyboard focus), so errors are ignored.
    """
    pid = os.getpid() if pid is None else pid
    script = f'tell application "System Events" to set frontmost of the first process whose unix id is {pid} to true'
    try:
        runner(["osascript", "-e", script], capture_output=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass  # not on a Mac, or too slow: fine


HINT = "↩ open     ⇥ complete     ⎋ close"


class LauncherWindow:
    def __init__(
        self,
        root: tk.Tk,
        engine,
        config,
        front=bring_to_front,
        confirm=messagebox.askyesno,
        style=default_style,
    ):
        self.root, self.engine, self.config = root, engine, config
        self.front, self.confirm, self.style = front, confirm, style
        self.theme = make_theme(config)
        self.state = LauncherState(rows=config.max_results)
        self.visible = False
        self.styled = False
        self._position = (0, config.window_top_offset)
        self._build()

    # ---- building the widgets -------------------------------------------- #

    def _build(self) -> None:
        root, config, t = self.root, self.config, self.theme
        root.title(config.window_title)
        root.resizable(False, False)
        root.configure(bg=t.background)
        characters = int(
            config.window_width / (t.row_size * 0.55)
        )  # about how many characters fit in a row

        # The "search bar": the text box (left) and the mode label (right) share one background.
        bar = tk.Frame(root, bg=t.input_background)
        bar.pack(fill="x", padx=14, pady=(8, 8))
        self.mode = tk.Label(
            bar,
            text="",
            bg=t.input_background,
            fg=t.muted,
            font=(t.font, t.small_size),
            padx=10,
        )
        self.mode.pack(side="right")
        self.input = CommandInput(bar, t, on_change=lambda _text: self.refresh())
        self.input.text.pack(side="left", fill="x", expand=True)

        self.list = ResultList(
            root,
            t,
            rows=config.max_results,
            characters=characters,
            on_click=self._clicked,
        )
        self.list.frame.pack(fill="x", padx=14)

        self.status = tk.Label(
            root,
            text=HINT,
            anchor="w",
            bg=t.background,
            fg=t.muted,
            font=(t.font, t.small_size),
        )
        self.status.pack(fill="x", padx=18, pady=(6, 10))

        # Keys. Returning "break" tells tkinter: "I handled it, do not do your normal thing".
        text = self.input.text
        text.bind("<Down>", lambda e: self._move(+1))
        text.bind("<Up>", lambda e: self._move(-1))
        text.bind("<Tab>", lambda e: self._autocomplete())
        text.bind("<Return>", lambda e: self._run_selected())
        root.bind("<Escape>", lambda e: self.hide())

    # ---- showing and hiding ---------------------------------------------- #

    def show(self) -> None:
        self.input.set("")
        self.refresh()
        self.root.update_idletasks()
        width = self.config.window_width
        self._position = (
            (self.root.winfo_screenwidth() - width) // 2,
            self.config.window_top_offset,
        )
        self._resize()
        self.root.deiconify()
        self.root.attributes("-topmost", True)  # above the other windows
        self.root.lift()
        if not self.styled and self.config.window_style == "borderless":
            self.root.update()  # the real (Cocoa) window must exist before we can style it
            self.styled = bool(
                self.style(self.config.window_title, self.theme.background)
            )
        self.front()
        self.input.focus()
        self.visible = True

    def _resize(self) -> None:
        """The window is as tall as its rows: few results, small window."""
        self.root.update_idletasks()
        x, y = self._position
        self.root.geometry(
            f"{self.config.window_width}x{self.root.winfo_reqheight()}+{x}+{y}"
        )

    def hide(self) -> None:
        self.root.withdraw()
        self.visible = False

    def toggle(self) -> None:
        self.hide() if self.visible else self.show()

    # ---- reacting to the user -------------------------------------------- #

    def refresh(self) -> None:
        """Ask the engine for suggestions for the current text and draw them."""
        typed = self.input.get()
        try:
            self.state.set_answer(self.engine.search(typed))
            self.status.config(text=HINT)
        except Exception as exc:  # the window must never die: show the problem instead
            self.state.clear()
            self.status.config(text=f"error: {exc}")
        try:
            self.input.paint_command(min(self.state.highlight, len(typed)))
            self.mode.config(text=mode_label(self.state.mode))
            self._draw_list()
        except Exception as exc:  # drawing must never fail silently: say it in the window and in the log
            import traceback

            traceback.print_exc()
            self.status.config(
                text=f"error drawing {len(self.state.results)} row(s): {exc}"
            )
        if self.visible:
            self._resize()

    def _draw_list(self) -> None:
        self.list.draw(self.state.visible, self.state.visible_selected)

    def _move(self, step: int) -> str:
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

    def _run_selected(self) -> str:
        item = self.state.current
        if item is None:
            return "break"
        if (
            item["kind"] == "prefix"
        ):  # a hint ("yt", "kill", ";p"): there is nothing to run yet, so write it and wait
            self.input.set(item["complete"])
            return "break"
        if item["confirm"] and not self.confirm(
            self.config.window_title,
            f"{item['title']}: are you sure?",
            parent=self.root,
        ):
            return "break"
        typed = self.input.get()
        result = self.engine.run(item["id"], typed)
        if (
            result.needs_force
        ):  # an app did not quit: only force quit if the user agrees
            question = f"{result.message}\n\nForce quit now?"
            if self.confirm(self.config.window_title, question, parent=self.root):
                result = self.engine.run(item["id"], typed, force=True)
        if result.ok:
            self.hide()
        else:
            self.status.config(text=f"error: {result.message}")
        return "break"
