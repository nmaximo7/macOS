"""
mytheme.py - colours, fonts and small text helpers of the window. No tkinter here, so it is easy to test.

The colours come from `window.colors` in conf/myconfiguration.json (see myconfig.DEFAULT_COLORS).

GUIDED TOUR: three small things, none of which needs a screen.
  hex_to_rgb           "#ff9f0a" -> (1.0, 0.62, 0.04): colours as Cocoa wants them (shared by mychrome, mytoast, mytimerdisplay).
  Theme / make_theme   ONE frozen object with all colours and font sizes, built from the config, passed to every widget. Widgets never read the
                       config for looks: change the theme in one place and everything follows (this is a "design token" idea in miniature).
  MODE_LABELS / mode_label   the text at the right of the search box. The engine reports a MODE ("kill", "emoji"...) and the window turns it into words here.
  shorten / row_texts  text fitting: a long snippet must not push the badge off the row.
WORKED EXAMPLE of fitting: row_texts with characters=60, title "Obsidian" (8 letters), badge "app" (3): room = 60 - 8 - 3 - 6 = 43 characters are left for the
subtitle (6 is a margin for the icon and spaces). shorten("a very long path ...", 43) keeps 42 characters and adds "…": 42 + 1 = 43.
"""

from __future__ import annotations

from dataclasses import dataclass

# What the small label at the right of the text box says for each mode the engine reports.
MODE_LABELS = {
    "run": "🚀 Applications",
    "kill": "💀 Close an app",
    "quicklink": "🔎 Web search",
    "snippets": "✂️ Snippets",
    "help": "📚 Help",
    "edit": "📝 Edit a file",
    "secret": "🔑 Secrets",
    "keep_secret": "🔐 Edit the secret file",
    "emoji": "😀 Emoji",
    "emoji_add": "⭐ Add an emoji to my_favorites",
    "emoji_remove": "⭐ Remove an emoji from my_favorites",
    "secret_set": "🔐 Save a secret in the Keychain",
    "execute": "▶️ Execute",
    "favorites": "⭐ Favorites",
}


@dataclass(frozen=True)
class Theme:
    font: str
    size: int  # the text box; rows use size - 4, small grey texts size - 8 (never below 10)
    background: str
    input_background: str
    text: str
    muted: str
    selection: str
    command: str

    # Sizes derived from the main one, with a FLOOR: max(size - 4, 12) is never below 12. Small fonts that cannot be read are a bug, not a preference.
    @property
    def row_size(self) -> int:
        return max(self.size - 4, 12)

    @property
    def small_size(self) -> int:
        return max(self.size - 8, 10)


def make_theme(config) -> Theme:
    colors = config.window_colors
    return Theme(
        font=config.window_font,
        size=config.window_font_size,
        background=colors["background"],
        input_background=colors["input_background"],
        text=colors["text"],
        muted=colors["muted"],
        selection=colors["selection"],
        command=colors["command"],
    )


def hex_to_rgb(color: str) -> tuple:
    """"#ff9f0a" (the "#" is optional) -> (1.0, 0.62, 0.04): the three 0..1 numbers Cocoa wants.

    The ONE copy of this helper (Step 20.14): mychrome, mytoast and mytimerdisplay used to have one each. int("ff", 16) reads hexadecimal (base 16);
    dividing by 255 maps 0..255 to 0..1. The slice i : i+2 for i in (0, 2, 4) picks the three pairs of the text without its "#".
    """
    h = color.lstrip("#")
    return tuple(int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))


def shorten(text: str, limit: int) -> str:
    """Cut a long text and end it with "…" so it fits in `limit` characters (a snippet can be a whole page)."""
    text = " ".join(text.split())  # new lines and runs of spaces become single spaces
    if limit < 2 or len(text) <= limit:
        return text if limit >= 2 else ""
    return text[: limit - 1].rstrip() + "…"


def mode_label(mode: str) -> str:
    return MODE_LABELS.get(mode, "")  # dict.get(key, default): an unknown mode gives "" (no label) instead of a KeyError


def row_texts(result: dict, characters: int) -> tuple:
    """(icon, title, subtitle, badge) of one row. The subtitle gets the room the title and badge leave."""
    title, badge = result.get("title", ""), result.get("badge", "")
    room = characters - len(title) - len(badge) - 6
    return result.get("icon", ""), title, shorten(result.get("subtitle", ""), room), badge
