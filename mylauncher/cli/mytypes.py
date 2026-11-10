"""
mytypes.py - the two little "shapes" of data that every other file shares.

An Item is one thing the launcher can do:      "Run Obsidian"   or   "Shutdown".
A Match is an Item plus how well it matched what the user typed (a score).

Everything else in the launcher (search, actions, the command line, later the window) only
moves Items and Matches around. Keeping them in ONE small file means that if you ever wonder
"what exactly is an item?", this is the only place to look.

Python concepts used here (explained in docs/03-implementation.md):
  * dataclass: a class that is just a list of named fields; Python writes __init__ for us.
  * frozen=True: after creation the object cannot be changed (fewer surprises).
  * tuple: a list that cannot be changed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    """One thing the launcher can do."""

    id: str  # unique name, used to pick an exact item: "app:Obsidian" or "cmd:shutdown"
    title: str  # what the user sees in the list: "Run Obsidian"
    kind: str  # "app" (open a program) or "command" (something else, e.g. shutdown)
    action: str  # which function in myactions.py does the work: "open_app" or "shutdown"
    target: str = ""  # for kind="app": the path of the .app folder, e.g. /Applications/Obsidian.app
    keywords: tuple = ()  # extra words that also find this item ("power off" finds Shutdown)
    confirm: bool = False  # True = ask "are you sure?" before doing it

    def to_dict(self) -> dict:
        """A plain dictionary, ready to be written as JSON (this is what the GUI will read)."""
        return {
            "id": self.id,
            "title": self.title,
            "kind": self.kind,
            "action": self.action,
            "target": self.target,
            "keywords": list(self.keywords),
            "confirm": self.confirm,
        }


@dataclass(frozen=True)
class Match:
    """An Item that matched a query, with its score (higher = better match)."""

    item: Item
    score: int

    def to_dict(self) -> dict:
        data = self.item.to_dict()
        data["score"] = self.score
        return data
