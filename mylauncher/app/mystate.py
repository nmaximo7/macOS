"""
mystate.py - what the window remembers: the suggestions, and which one is selected.

This file has NO tkinter in it, on purpose: all the "thinking" of the window (move the selection,
wrap around at the ends, what does Tab write) lives here and is tested without opening a window.
mywindow.py only draws this state and passes it the key presses.
"""

from __future__ import annotations


class LauncherState:
    def __init__(self, rows: int = 8):
        self.rows = rows  # how many rows fit in the window; a longer list scrolls
        self.results: list = []  # item dictionaries (as in the engine's JSON), best first
        self.completion: str = ""  # what Tab writes
        self.selected: int = 0  # index in `results`
        self.top: int = 0  # index of the first visible result (scrolling)
        self.mode: str = "normal"  # what the engine understood: normal, run, kill, quicklink, snippets
        self.highlight: int = 0  # how many characters at the start of the text are the recognised command

    def set_answer(self, answer: dict) -> None:
        """Take the engine's answer to a search. The selection goes back to the best match."""
        self.results = list(answer.get("results", []))
        self.completion = answer.get("completion", "")
        self.selected = 0
        self.top = 0
        self.mode = answer.get("mode", "normal")
        self.highlight = int(answer.get("highlight", 0))

    def clear(self) -> None:
        self.set_answer({})

    def move(self, step: int) -> None:
        """step=+1 moves down, -1 moves up; after the last comes the first (and the other way round)."""
        if self.results:
            self.selected = (self.selected + step) % len(self.results)
            self._scroll_into_view()

    def _scroll_into_view(self) -> None:
        """Move `top` the least possible so the selected row is one of the visible ones."""
        if self.selected < self.top:
            self.top = self.selected
        elif self.selected >= self.top + self.rows:
            self.top = self.selected - self.rows + 1

    @property
    def visible(self) -> list:
        """The results that are on screen now."""
        return self.results[self.top : self.top + self.rows]

    @property
    def visible_selected(self) -> int:
        """Which of the visible rows is selected (0 = the first visible one)."""
        return self.selected - self.top

    def select_visible(self, row: int) -> None:
        """The user clicked the `row`-th visible row."""
        if 0 <= row < len(self.visible):
            self.selected = self.top + row

    @property
    def current(self) -> dict | None:
        """The selected item, or None when there are no suggestions."""
        return self.results[self.selected] if self.results else None

    def tab_text(self, typed: str) -> str:
        """What the text box should contain after pressing Tab: the completion, or what is already there."""
        return self.completion if self.results and self.completion else typed
