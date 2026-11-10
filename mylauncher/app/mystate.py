"""
mystate.py - what the window remembers: the suggestions, and which one is selected.

This file has NO tkinter in it, on purpose: all the "thinking" of the window (move the selection,
wrap around at the ends, what does Tab write) lives here and is tested without opening a window.
mywindow.py only draws this state and passes it the key presses.
"""

from __future__ import annotations


class LauncherState:
    def __init__(self):
        self.results: list = []  # item dictionaries (as in the engine's JSON), best first
        self.completion: str = ""  # what Tab writes
        self.selected: int = 0  # index in `results`

    def set_answer(self, answer: dict) -> None:
        """Take the engine's answer to a search. The selection goes back to the best match."""
        self.results = list(answer.get("results", []))
        self.completion = answer.get("completion", "")
        self.selected = 0

    def clear(self) -> None:
        self.set_answer({})

    def move(self, step: int) -> None:
        """step=+1 moves down, -1 moves up; after the last comes the first (and the other way round)."""
        if self.results:
            self.selected = (self.selected + step) % len(self.results)

    @property
    def current(self) -> dict | None:
        """The selected item, or None when there are no suggestions."""
        return self.results[self.selected] if self.results else None

    def tab_text(self, typed: str) -> str:
        """What the text box should contain after pressing Tab: the completion, or what is already there."""
        return self.completion if self.results and self.completion else typed
