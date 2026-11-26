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

LINE-BY-LINE READING GUIDE ---------------------------------------------------------------------------
  `from __future__ import annotations`   lets us write type hints like `int | None` and refer to classes
                                         defined later in the file; it changes nothing at run time.
  `class ConfigError(Exception)`         a NEW KIND OF ERROR. `raise ConfigError("...")` stops the normal flow and
                                         jumps to the nearest `except ConfigError`. Its own class lets callers catch
                                         "settings problems" without also catching unrelated bugs.
  DEFAULT_ICONS / KIND_LABELS            two dictionaries (key -> value) used when an Item does not choose its own.
                                         `DEFAULT_ICONS.get("app", "")` = the value, or "" if the key is missing.
  class Item                             ONE ROW. 12 fields; only id, title, kind and action are required.
  class Match                            an Item plus its score.
  to_dict()                              turns an object into a plain dict, because JSON has no "objects": this is
                                         the bridge between the engine (Python objects) and the window (JSON text).
Example of an Item and its JSON form (what `ml search --json` prints for each result):

    Item(id="app:Obsidian", title="Run Obsidian", kind="app", action="open_app", target="/Applications/Obsidian.app")
    -> {"id": "app:Obsidian", "title": "Run Obsidian", "kind": "app", "action": "open_app",
        "target": "/Applications/Obsidian.app", "keywords": [], "confirm": false, "complete": "",
        "subtitle": "", "detail": "", "icon": "🚀", "badge": "Application"}
Note icon and badge: they were empty in the Item, so to_dict() filled them from the two dictionaries.
"""

from __future__ import annotations

from dataclasses import dataclass


class ConfigError(Exception):
    """A configuration file (myconfiguration.json or quicklinks.json) is missing or wrong.

    It lives here, in the file everybody imports, so that myconfig.py and myquicklinks.py can both
    raise it without importing each other.
    """


# What the window shows when an item does not choose its own emoji / label. One place to change them.
DEFAULT_ICONS = {"app": "🚀", "command": "⚡", "prefix": "💡", "quicklink": "🔎", "kill": "💀", "snippet": "✂️", "help": "📚", "edit": "📝", "execute": "▶️"}
KIND_LABELS = {"app": "Application", "command": "Command", "prefix": "Hint", "quicklink": "Quicklink", "kill": "Running app", "snippet": "Snippet", "help": "Help", "edit": "File", "execute": "Execute"}


@dataclass(frozen=True)
class Item:
    """One thing the launcher can do."""

    # Fields WITHOUT a default (`= ...`) must be given when you create an Item; fields WITH one are optional.
    # Python requires the required fields first, which is why id/title/kind/action come before the rest.
    id: str  # unique name, used to pick an exact item: "app:Obsidian" or "cmd:shutdown"
    title: str  # what the user sees in the list: "Run Obsidian"
    kind: str  # "app", "command" (e.g. shutdown), "prefix" (a word that needs more text after it: "yt", "kill"),
    #            "quicklink" (a web search ready to open), "kill" (a running app that can be closed)
    #            or "snippet" (a piece of text from your Espanso files, copied to the clipboard)
    action: str  # which function in myactions.py does the work: "open_app" or "shutdown"
    target: str = ""  # for kind="app": the path of the .app folder, e.g. /Applications/Obsidian.app
    # (a tuple, not a list, because a frozen object should hold only unchangeable things; `()` is the empty tuple)
    keywords: tuple = ()  # extra words that also find this item ("power off" finds Shutdown)
    confirm: bool = False  # True = ask "are you sure?" before doing it
    complete: str = ""  # what Tab writes in the search box; empty = the title in lower case
    subtitle: str = ""  # grey extra text shown after the title (not searched), e.g. the text of a snippet
    icon: str = ""  # an emoji shown at the start of the row; empty = the default for the kind (DEFAULT_ICONS)
    detail: str = ""  # the long text the window shows when you open a help row (function source, alias, ...)
    badge: str = ""  # small label at the end of the row; empty = the default for the kind (KIND_LABELS)

    def to_dict(self) -> dict:
        """A plain dictionary, ready to be written as JSON (this is what the GUI will read).

        `list(self.keywords)` because JSON has lists but no tuples. `self.icon or DEFAULT_ICONS.get(...)` means
        "the icon if it is not empty, otherwise the default of the kind": `or` returns its first non-empty side.
        """
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
            "detail": self.detail,
            "icon": self.icon or DEFAULT_ICONS.get(self.kind, ""),
            "badge": self.badge or KIND_LABELS.get(self.kind, ""),
        }


@dataclass(frozen=True)
class Match:
    """An Item that matched a query, with its score (higher = better match)."""

    item: Item
    score: int

    def to_dict(self) -> dict:
        """The item's dict plus the score. This is one entry of "results" in `ml search --json`."""
        data = self.item.to_dict()
        data["score"] = self.score
        return data
