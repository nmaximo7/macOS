"""
mychrome.py - makes the window look like a launcher instead of a normal window (macOS only).

A normal macOS window has a title bar with three buttons (red, yellow, green). tkinter cannot remove
them, but the window underneath is a real Cocoa window (NSWindow) and PyObjC (the same bridge the
menu bar uses) can talk to it:

    * the title is hidden and the title bar becomes transparent (it takes the colour of the window),
    * the three buttons are hidden,
    * you can drag the window from anywhere,
    * the window floats above the others.

It is deliberately NOT a borderless window ("overrideredirect" in tkinter): such a window cannot receive
the keyboard on macOS, and a launcher you cannot type into is no use.

If PyObjC is missing or anything fails, we say so and keep the normal window: it still works.
"""

from __future__ import annotations

import sys

NS_WINDOW_TITLE_HIDDEN = 1
NS_BUTTONS = (0, 1, 2)  # NSWindowCloseButton, NSWindowMiniaturizeButton, NSWindowZoomButton
NS_FLOATING_WINDOW_LEVEL = 3


def hex_to_rgb(color: str) -> tuple:
    """"#ff9f0a" -> (1.0, 0.62, 0.04): the 0..1 numbers Cocoa wants."""
    return tuple(int(color[i : i + 2], 16) / 255 for i in (1, 3, 5))


def apply_style(title: str, background: str, appkit=None, log=print) -> bool:
    """Style the window called `title`. True when it worked. `appkit` is replaced by a fake in tests."""
    if appkit is None:
        try:
            import AppKit as appkit
        except ImportError:
            log("window style: PyObjC (AppKit) is not installed, keeping the normal window (pip install pyobjc-framework-Cocoa)")
            return False
    try:
        windows = [w for w in appkit.NSApp.windows() if str(w.title()) == title]
        if not windows:
            log(f"window style: no window called {title!r} found, keeping the normal window")
            return False
        window = windows[0]
        window.setTitleVisibility_(NS_WINDOW_TITLE_HIDDEN)
        window.setTitlebarAppearsTransparent_(True)
        window.setMovableByWindowBackground_(True)
        window.setLevel_(NS_FLOATING_WINDOW_LEVEL)
        for button in NS_BUTTONS:
            widget = window.standardWindowButton_(button)
            if widget is not None:
                widget.setHidden_(True)
        r, g, b = hex_to_rgb(background)
        window.setBackgroundColor_(appkit.NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, 1.0))
        return True
    except Exception as exc:  # noqa: BLE001  (Objective-C errors come in many types; none must break the launcher)
        log(f"window style: could not style the window ({exc}); keeping the normal window")
        return False


def default_style(title: str, background: str) -> bool:
    return apply_style(title, background) if sys.platform == "darwin" else False
