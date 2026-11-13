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


class ConfigError(Exception):
    """A configuration file (myconfiguration.json or quicklinks.json) is missing or wrong.

    It lives here, in the file everybody imports, so that myconfig.py and myquicklinks.py can both
    raise it without importing each other.
    """


# What the window shows when an item does not choose its own emoji / label. One place to change them.
DEFAULT_ICONS = {"app": "🚀", "command": "⚡", "prefix": "💡", "quicklink": "🔎", "kill": "💀", "snippet": "✂️"}
KIND_LABELS = {"app": "Application", "command": "Command", "prefix": "Hint", "quicklink": "Quicklink", "kill": "Running app", "snippet": "Snippet"}


@dataclass(frozen=True)
class Item:
    """One thing the launcher can do."""

    id: str  # unique name, used to pick an exact item: "app:Obsidian" or "cmd:shutdown"
    title: str  # what the user sees in the list: "Run Obsidian"
    kind: str  # "app", "command" (e.g. shutdown), "prefix" (a word that needs more text after it: "yt", "kill"),
    #            "quicklink" (a web search ready to open), "kill" (a running app that can be closed)
    #            or "snippet" (a piece of text from your Espanso files, copied to the clipboard)
    action: str  # which function in myactions.py does the work: "open_app" or "shutdown"
    target: str = ""  # for kind="app": the path of the .app folder, e.g. /Applications/Obsidian.app
    keywords: tuple = ()  # extra words that also find this item ("power off" finds Shutdown)
    confirm: bool = False  # True = ask "are you sure?" before doing it
    complete: str = ""  # what Tab writes in the search box; empty = the title in lower case
    subtitle: str = ""  # grey extra text shown after the title (not searched), e.g. the text of a snippet
    icon: str = ""  # an emoji shown at the start of the row; empty = the default for the kind (DEFAULT_ICONS)
    badge: str = ""  # small label at the end of the row; empty = the default for the kind (KIND_LABELS)

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
            "complete": self.complete,
            "subtitle": self.subtitle,
            "icon": self.icon or DEFAULT_ICONS.get(self.kind, ""),
            "badge": self.badge or KIND_LABELS.get(self.kind, ""),
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
