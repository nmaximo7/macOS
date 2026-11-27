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

GUIDED TOUR: one class, MenuBar, and one lesson: HOW PYTHON CAN BE CALLED BY APPLE'S FRAMEWORK.
  load_appkit   import the real PyObjC pieces and bundle them in a SimpleNamespace (a bag of attributes), so a test can pass a fake bag with the same names.
  MenuBar.start build, in this order: a `Target` object (the receiver of clicks) -> an NSMenu with one NSMenuItem per entry -> a status item in the menu bar.
  set_title / stop   change the text of the icon (the timer countdown goes here); remove the icon.
WHY A CLASS INSIDE A METHOD? Cocoa works by sending MESSAGES to objects. For a menu item to call us, it needs a target object that is a real Cocoa object
(subclass of NSObject) with a method whose name matches the item's "action". Our Python method `chosen_` becomes the Objective-C selector `chosen:` (each
underscore stands for a colon), which is why the item is created with the action string "chosen:". The class is defined INSIDE start() because it needs `ns`
(the possibly-fake AppKit) and a class body can use variables of the function around it.
Each item carries a `representedObject` (a free label we set: the word "toggle" or "quit"); the click handler reads it back and calls on_choice(word). One handler
serves every entry: data in the item, one function in the target.
THE MOST IMPORTANT LINE IS A COMMENT in __init__: self._item and self._target must stay referenced. In Python, an object nobody refers to is deleted;
Cocoa does not count Python's references, so if we dropped them the icon would vanish. (Same lesson as `power_watch` in chapter 14.)
Not tested on a real Mac here beyond the fake AppKit.
"""

from __future__ import annotations

from types import SimpleNamespace

# (text in the menu, word given to on_choice)
DEFAULT_ENTRIES = (("Show / hide launcher", "toggle"), ("Quit mylauncher", "quit"))

# An "accessory" app has no Dock icon and no menu bar of its own: exactly a menu bar utility. (hide_dock in the settings switches this on.)
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
                # Objective-C objects are created in TWO steps: alloc() (reserve memory) then an init method (set up). `objc.super(...).init()` calls the parent's
                # init, as `super().__init__()` would in plain Python; the pattern `self = ...init()` is the Objective-C idiom.
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

        # The menu bar is one shared system object; we ask it for a new item as wide as its title needs (NSVariableStatusItemLength).
        self._item = ns.NSStatusBar.systemStatusBar().statusItemWithLength_(ns.NSVariableStatusItemLength)
        self._item.button().setTitle_(self.title)
        self._item.setMenu_(menu)
        if self.hide_dock:
            ns.NSApplication.sharedApplication().setActivationPolicy_(ACCESSORY_POLICY)
        self._ns = ns

    def set_title(self, text: str) -> None:
        """Change the text of the icon (the timer shows its countdown here). Never raises."""
        try:
            if self._item is not None:
                self._item.button().setTitle_(text)
        except Exception:  # noqa: BLE001 - a title that cannot change must not stop anything
            pass

    def stop(self) -> None:
        if self._item is not None:
            self._ns.NSStatusBar.systemStatusBar().removeStatusItem_(self._item)
            self._item = self._target = None
