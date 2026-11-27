"""
mywidgets.py - the two parts the window is made of: the text box and the list of rows.

CommandInput  a one-line text box where the recognised command (kill, yt, ;p ...) is painted in colour.
              (A plain tkinter Entry cannot colour part of its text; a Text widget can, with "tags".)
ResultList    the rows under it: emoji, title, grey information, and a small label at the right.

They only DRAW. What a key does is decided in mywindow.py, what a row contains in the engine.

GUIDED TOUR: three classes, each wrapping a few tkinter widgets so mywindow.py can say `self.list.draw(...)` instead of managing labels.
  CommandInput  one Text widget + a TAG ("command") that colours the first N characters. get/set/paint_command/focus, and a change detector (_modified/_changed).
  ResultList    a fixed set of rows, built ONCE (_make_row), then re-filled by draw() and re-coloured by select(). Rows beyond the results are hidden, not destroyed.
  DetailView    a read-only scrollable Text that takes the list's place (the full text of a help row).
IDEA TO KEEP: CREATE WIDGETS ONCE, CHANGE THEIR TEXT LATER. Creating and destroying widgets at every keystroke would flicker and be slow. So ResultList makes
`rows` rows at start-up, and draw() only calls .config(text=...) and pack()/pack_forget().
Try it:   python3 app/mylauncher_app.py --show      (the window with the engine; type "ob")
"""

from __future__ import annotations

import tkinter as tk

from mytheme import row_texts


class CommandInput:
    def __init__(self, parent, theme, on_change):
        self.on_change, self._last = on_change, ""
        # Why a Text and not an Entry: an Entry cannot colour a PART of its text; a Text can (with tags). Height 1 + wrap="none" makes it look like one line.
        # bd/highlightthickness/relief remove the borders; insertbackground is the colour of the blinking cursor.
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
        # <<Modified>> is a VIRTUAL event ("something changed in this Text"): the way to hear every edit (typing, paste, delete) with one binding.
        self.text.bind("<<Modified>>", self._modified)

    def get(self) -> str:
        # Text positions are "line.column" strings: "1.0" = line 1, column 0 (the start). "end-1c" = the end minus one character, because Tk always keeps a
        # final newline that is not yours. A pasted newline becomes a space: this is a one-line box.
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
            self.text.tag_add("command", "1.0", f"1.{length}")  # from 1.0 up to 1.<length>: the first `length` characters of line 1

    def focus(self) -> None:
        self.text.focus_force()

    def _modified(self, _event) -> None:
        # tkinter sets an "edit_modified" flag at each change and only fires <<Modified>> when it goes from False to True, so we must RESET it to hear the next one.
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
        # A list comprehension that BUILDS the rows: [row0, row1, ..., row7]. Each row is a dict of widgets.
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
            # `i=index` in the lambda is the classic CLOSURE TRAP fix. Without it, every lambda would remember the variable `index` itself (not its value then),
            # and all rows would report the LAST index. A default argument is evaluated when the lambda is CREATED, so each one keeps its own number.
            widget.bind("<Button-1>", lambda _e, i=index: self.on_click(i))
        return row

    def draw(self, results: list, selected: int) -> None:
        """Show `results` (at most as many as there are rows); `selected` is the row to highlight."""
        # The rows are a fixed pool. Show the first `shown` of them, hide the others (pack_forget keeps them for next time).
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


class DetailView:
    """A read-only, scrollable text that takes the place of the list: the full text of a help row
    (the source of a function, an alias with its comment, a cheat sheet...)."""

    LINES = 14  # visible lines

    def __init__(self, parent, theme):
        self.frame = tk.Frame(parent, bg=theme.background)
        self.title = tk.Label(self.frame, bg=theme.background, fg=theme.command, font=(theme.font, theme.row_size, "bold"), anchor="w")
        self.title.pack(fill="x", padx=10, pady=(4, 2))
        self.text = tk.Text(
            self.frame, height=self.LINES, wrap="word", bd=0, highlightthickness=0, relief="flat", padx=10, pady=6,
            font=("Menlo", theme.small_size + 2), bg=theme.input_background, fg=theme.text, selectbackground=theme.selection,
            cursor="arrow",
        )
        self.text.pack(fill="x")
        # A Text in state "disabled" ignores typing, which is what we want to READ in; but it also ignores our own insert(), so show() switches it to "normal" for
        # a moment and back. yview_moveto(0) scrolls to the top; yview_scroll(n, "units") scrolls n lines.
        self.text.config(state="disabled")  # nobody types here: it is only for reading

    def show(self, title: str, body: str) -> None:
        self.title.config(text=title)
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", body)
        self.text.config(state="disabled")
        self.text.yview_moveto(0)

    def scroll(self, lines: int) -> None:
        self.text.yview_scroll(lines, "units")

    def content(self) -> str:
        return self.text.get("1.0", "end-1c")
