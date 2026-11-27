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

GUIDED TOUR: this file is a BRIDGE to the Mac's own window system. Background:
  tkinter draws the window CONTENT, but the frame around it (title bar, buttons) belongs to macOS. Every macOS window is an NSWindow object (Cocoa, written in
  Objective-C). PyObjC lets Python call those objects. Objective-C method names look odd to a Python eye: `setTitleVisibility_(1)` is `setTitleVisibility:`
  with an argument (each colon becomes an underscore).
  hex_to_rgb      now lives in mytheme.py (shared with the toast and the timer display); it is imported here, so `from mychrome import hex_to_rgb` still works.
  apply_style     find OUR window among all windows of the app by its title, then call the Cocoa setters. The NS_* constants are Apple's numbers (magic numbers
                  copied from Apple's documentation; they are named here so the code reads).
  default_style   only on macOS (sys.platform == "darwin"); on Linux (the tests) it returns False.
The `appkit` PARAMETER is dependency injection again: a test passes a fake AppKit and checks which setters were called, with no Mac. The big `except Exception`
is deliberate and marked: Objective-C errors come in many types, and a missing decoration must never stop a launcher.
Not tested on a real Mac in this project's test-suite beyond the fake; if the title bar looks wrong, the log line "window style:" says why.
"""

from __future__ import annotations

import sys

from mytheme import hex_to_rgb  # noqa: F401 - the one shared copy; still importable from here (tests, older code)

NS_WINDOW_TITLE_HIDDEN = 1
NS_BUTTONS = (0, 1, 2)  # NSWindowCloseButton, NSWindowMiniaturizeButton, NSWindowZoomButton
NS_FLOATING_WINDOW_LEVEL = 3


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
