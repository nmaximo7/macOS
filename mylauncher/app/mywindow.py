"""
mywindow.py - the window, drawn with tkinter (Python's standard graphical library).

What you see: a text box, and under it the list of suggestions.
What the keys do:
    typing        new suggestions (lowercase or UPPERCASE, it is the same)
    Up / Down     move the selection (wraps around)
    Tab           autocomplete: writes the first suggestion in the text box
    Enter         do the selected item (Shutdown asks "are you sure?" first)
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

from mystate import LauncherState


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


class LauncherWindow:
    def __init__(self, root: tk.Tk, engine, config, front=bring_to_front, confirm=messagebox.askyesno):
        self.root, self.engine, self.config = root, engine, config
        self.front, self.confirm = front, confirm
        self.state = LauncherState()
        self.visible = False
        self._build()

    # ---- building the widgets -------------------------------------------- #

    def _build(self) -> None:
        root, config = self.root, self.config
        root.title(config.window_title)
        root.resizable(False, False)
        font = ("Helvetica", config.window_font_size)

        self.text = tk.StringVar()
        self.entry = tk.Entry(root, textvariable=self.text, font=font, width=1)  # width=1: the window width decides
        self.entry.pack(fill="x", padx=12, pady=(12, 6))

        self.listbox = tk.Listbox(
            root, font=font, height=config.max_results, activestyle="none", exportselection=False, takefocus=0
        )
        self.listbox.pack(fill="both", padx=12)

        self.status = tk.Label(root, text="", anchor="w", font=("Helvetica", max(config.window_font_size - 8, 9)))
        self.status.pack(fill="x", padx=12, pady=(4, 10))

        # Every time the text changes -> search again.
        self.text.trace_add("write", lambda *_: self.refresh())
        # Keys. Returning "break" tells tkinter: "I handled it, do not do your normal thing".
        self.entry.bind("<Down>", lambda e: self._move(+1))
        self.entry.bind("<Up>", lambda e: self._move(-1))
        self.entry.bind("<Tab>", lambda e: self._autocomplete())
        self.entry.bind("<Return>", lambda e: self._run_selected())
        root.bind("<Escape>", lambda e: self.hide())

    # ---- showing and hiding ---------------------------------------------- #

    def show(self) -> None:
        self.text.set("")  # also triggers refresh()
        self.refresh()
        self.root.update_idletasks()
        width = self.config.window_width
        x = (self.root.winfo_screenwidth() - width) // 2
        self.root.geometry(f"{width}x{self.root.winfo_reqheight()}+{x}+{self.config.window_top_offset}")
        self.root.deiconify()
        self.root.attributes("-topmost", True)  # above the other windows
        self.root.lift()
        self.front()
        self.entry.focus_force()
        self.visible = True

    def hide(self) -> None:
        self.root.withdraw()
        self.visible = False

    def toggle(self) -> None:
        self.hide() if self.visible else self.show()

    # ---- reacting to the user -------------------------------------------- #

    def refresh(self) -> None:
        """Ask the engine for suggestions for the current text and draw them."""
        try:
            self.state.set_answer(self.engine.search(self.text.get()))
            self.status.config(text="")
        except Exception as exc:  # the window must never die: show the problem instead
            self.state.clear()
            self.status.config(text=f"error: {exc}")
        self._draw_list()

    def _draw_list(self) -> None:
        self.listbox.delete(0, "end")
        for result in self.state.results:
            self.listbox.insert("end", result["title"])
        self._draw_selection()

    def _draw_selection(self) -> None:
        self.listbox.selection_clear(0, "end")
        if self.state.current is not None:
            self.listbox.selection_set(self.state.selected)
            self.listbox.see(self.state.selected)

    def _move(self, step: int) -> str:
        self.state.move(step)
        self._draw_selection()
        return "break"

    def _autocomplete(self) -> str:
        wanted = self.state.tab_text(self.text.get())
        if wanted != self.text.get():
            self.text.set(wanted)
            self.entry.icursor("end")
        return "break"  # without this, Tab would jump to another widget

    def _run_selected(self) -> str:
        item = self.state.current
        if item is None:
            return "break"
        if item["confirm"] and not self.confirm(self.config.window_title, f"{item['title']}: are you sure?", parent=self.root):
            return "break"
        ok, message = self.engine.run(item["id"])
        if ok:
            self.hide()
        else:
            self.status.config(text=f"error: {message}")
        return "break"
