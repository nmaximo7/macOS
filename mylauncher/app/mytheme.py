"""
mytheme.py - colours, fonts and small text helpers of the window. No tkinter here, so it is easy to test.

The colours come from `window.colors` in conf/myconfiguration.json (see myconfig.DEFAULT_COLORS).
"""

from __future__ import annotations

from dataclasses import dataclass

# What the small label at the right of the text box says for each mode the engine reports.
MODE_LABELS = {
    "run": "🚀 Applications",
    "kill": "💀 Close an app",
    "quicklink": "🔎 Web search",
    "snippets": "✂️ Snippets",
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


def shorten(text: str, limit: int) -> str:
    """Cut a long text and end it with "…" so it fits in `limit` characters (a snippet can be a whole page)."""
    text = " ".join(text.split())  # new lines and runs of spaces become single spaces
    if limit < 2 or len(text) <= limit:
        return text if limit >= 2 else ""
    return text[: limit - 1].rstrip() + "…"


def mode_label(mode: str) -> str:
    return MODE_LABELS.get(mode, "")


def row_texts(result: dict, characters: int) -> tuple:
    """(icon, title, subtitle, badge) of one row. The subtitle gets the room the title and badge leave."""
    title, badge = result.get("title", ""), result.get("badge", "")
    room = characters - len(title) - len(badge) - 6
    return result.get("icon", ""), title, shorten(result.get("subtitle", ""), room), badge
