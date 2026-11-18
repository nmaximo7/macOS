"""
mymenubar.py - the little icon in the macOS menu bar (top right of the screen), with a menu.

    ⌘  ->  Show / hide launcher
           Quit mylauncher

tkinter cannot make menu bar icons, so here we talk to macOS directly with PyObjC (the library that
lets Python call Apple's own "AppKit" framework; it is installed together with pynput).

The pieces of AppKit we use (names as Apple writes them):
    NSStatusBar      the menu bar itself.  statusItemWithLength_(...) adds one icon to it.
    NSMenu / NSMenuItem   the drop-down menu. Each item has a target (who is told) and an action (what is called).
    NSObject         the base class for something that can receive that call: our small `Target` class.

Rules of this project:
  * The menu does not touch the window. When you choose an entry, `on_choice("toggle")` is called; the
    application puts that word in the same queue the hotkey uses, and the main loop acts on it.
  * Everything can fail softly: if AppKit is missing or macOS refuses, `start()` raises and the
    application prints a warning and runs without the icon.
  * AppKit is imported only inside start(), and can be replaced (the `appkit` argument), so the tests
    run on any machine with a fake AppKit. The REAL AppKit has only been exercised on a Mac by you.
"""

from __future__ import annotations

from types import SimpleNamespace

# (text in the menu, word given to on_choice)
DEFAULT_ENTRIES = (("Show / hide launcher", "toggle"), ("Quit mylauncher", "quit"))

ACCESSORY_POLICY = 1  # NSApplicationActivationPolicyAccessory: an app without a Dock icon


def load_appkit() -> SimpleNamespace:
    """Import the real PyObjC / AppKit. Raises RuntimeError with the fix when it is not installed."""
    try:
        import objc
        from AppKit import (
            NSApplication,
            NSMenu,
            NSMenuItem,
            NSObject,
            NSStatusBar,
            NSVariableStatusItemLength,
        )
    except ImportError:
        raise RuntimeError("PyObjC is not installed: run  .venv/bin/pip install pyobjc-framework-Cocoa") from None
    return SimpleNamespace(
        objc=objc,
        NSApplication=NSApplication,
        NSMenu=NSMenu,
        NSMenuItem=NSMenuItem,
        NSObject=NSObject,
        NSStatusBar=NSStatusBar,
        NSVariableStatusItemLength=NSVariableStatusItemLength,
    )


class MenuBar:
    def __init__(self, title: str, on_choice, entries=DEFAULT_ENTRIES, hide_dock: bool = False, appkit=None):
        self.title, self.on_choice, self.entries, self.hide_dock = title, on_choice, entries, hide_dock
        self._appkit = appkit
        self._item = None  # the NSStatusItem
        self._target = None  # the object that receives the menu clicks
        # Both must stay referenced as long as the icon lives: if Python forgot them, the icon would vanish.

    def start(self) -> None:
        ns = self._appkit or load_appkit()

        class Target(ns.NSObject):
            """Receives the click on a menu entry. The name `chosen_` becomes the Objective-C selector `chosen:`."""

            def initWithCallback_(self, callback):
                self = ns.objc.super(Target, self).init()
                if self is None:
                    return None
                self._callback = callback
                return self

            def chosen_(self, sender):
                self._callback(str(sender.representedObject()))

        self._target = Target.alloc().initWithCallback_(self.on_choice)

        menu = ns.NSMenu.alloc().init()
        for text, word in self.entries:
            entry = ns.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(text, "chosen:", "")
            entry.setTarget_(self._target)
            entry.setRepresentedObject_(word)
            menu.addItem_(entry)

        self._item = ns.NSStatusBar.systemStatusBar().statusItemWithLength_(ns.NSVariableStatusItemLength)
        self._item.button().setTitle_(self.title)
        self._item.setMenu_(menu)
        if self.hide_dock:
            ns.NSApplication.sharedApplication().setActivationPolicy_(ACCESSORY_POLICY)
        self._ns = ns

    def stop(self) -> None:
        if self._item is not None:
            self._ns.NSStatusBar.systemStatusBar().removeStatusItem_(self._item)
            self._item = self._target = None
