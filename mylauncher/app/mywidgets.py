"""
mywidgets.py - the two parts the window is made of: the text box and the list of rows.

CommandInput  a one-line text box where the recognised command (kill, yt, ;p ...) is painted in colour.
              (A plain tkinter Entry cannot colour part of its text; a Text widget can, with "tags".)
ResultList    the rows under it: emoji, title, grey information, and a small label at the right.

They only DRAW. What a key does is decided in mywindow.py, what a row contains in the engine.
"""

from __future__ import annotations

import tkinter as tk

from mytheme import row_texts


class CommandInput:
    def __init__(self, parent, theme, on_change):
        self.on_change, self._last = on_change, ""
        self.text = tk.Text(
            parent,
            height=1,
            wrap="none",
            bd=0,
            highlightthickness=0,
            relief="flat",
            padx=10,
            pady=8,
            font=(theme.font, theme.size),
            bg=theme.input_background,
            fg=theme.text,
            insertbackground=theme.text,
            selectbackground=theme.selection,
            selectforeground=theme.text,
            undo=False,
        )
        # A "tag" is a named style for a range of characters. The recognised command gets this one.
        self.text.tag_configure("command", foreground=theme.command, font=(theme.font, theme.size, "bold"))
        self.text.bind("<<Modified>>", self._modified)

    def get(self) -> str:
        return self.text.get("1.0", "end-1c").replace("\n", " ")

    def set(self, value: str) -> None:
        self.text.delete("1.0", "end")
        self.text.insert("1.0", value)
        self.text.mark_set("insert", "end")
        self._changed()

    def end(self) -> None:
        self.text.mark_set("insert", "end")

    def paint_command(self, length: int) -> None:
        """Colour the first `length` characters (0 = nothing is recognised)."""
        self.text.tag_remove("command", "1.0", "end")
        if length > 0:
            self.text.tag_add("command", "1.0", f"1.{length}")

    def focus(self) -> None:
        self.text.focus_force()

    def _modified(self, _event) -> None:
        if self.text.edit_modified():  # tkinter sets this flag at every change; we reset it to hear the next one
            self.text.edit_modified(False)
            self._changed()

    def _changed(self) -> None:
        value = self.get()
        if value != self._last:  # the same text twice (we also get called by set()) does not search twice
            self._last = value
            self.on_change(value)


class ResultList:
    def __init__(self, parent, theme, rows: int, characters: int, on_click):
        self.theme, self.characters, self.on_click = theme, characters, on_click
        self.frame = tk.Frame(parent, bg=theme.background)
        self.rows = [self._make_row(i) for i in range(rows)]
        self.shown = 0

    def _make_row(self, index: int) -> dict:
        t = self.theme
        frame = tk.Frame(self.frame, bg=t.background, padx=10, pady=5)
        icon = tk.Label(frame, bg=t.background, fg=t.text, font=(t.font, t.row_size), width=2)
        badge = tk.Label(frame, bg=t.background, fg=t.muted, font=(t.font, t.small_size))
        title = tk.Label(frame, bg=t.background, fg=t.text, font=(t.font, t.row_size), anchor="w")
        subtitle = tk.Label(frame, bg=t.background, fg=t.muted, font=(t.font, t.small_size), anchor="w")
        icon.pack(side="left")
        badge.pack(side="right")
        title.pack(side="left", padx=(4, 10))
        subtitle.pack(side="left", fill="x")
        row = {"frame": frame, "icon": icon, "title": title, "subtitle": subtitle, "badge": badge}
        for widget in (frame, icon, title, subtitle, badge):
            widget.bind("<Button-1>", lambda _e, i=index: self.on_click(i))
        return row

    def draw(self, results: list, selected: int) -> None:
        """Show `results` (at most as many as there are rows); `selected` is the row to highlight."""
        self.shown = min(len(results), len(self.rows))
        for index, row in enumerate(self.rows):
            if index < self.shown:
                icon, title, subtitle, badge = row_texts(results[index], self.characters)
                row["icon"].config(text=icon)
                row["title"].config(text=title)
                row["subtitle"].config(text=subtitle)
                row["badge"].config(text=badge)
                row["frame"].pack(fill="x")
            else:
                row["frame"].pack_forget()
        self.select(selected)

    def select(self, selected: int) -> None:
        t = self.theme
        for index, row in enumerate(self.rows[: self.shown]):
            color = t.selection if index == selected else t.background
            for key in ("frame", "icon", "title", "subtitle", "badge"):
                row[key].config(bg=color)

    def texts(self) -> list:
        """What the visible rows say, for tests: [(icon, title, subtitle, badge), ...]."""
        return [tuple(row[k].cget("text") for k in ("icon", "title", "subtitle", "badge")) for row in self.rows[: self.shown]]
