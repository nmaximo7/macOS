"""app/mymenubar.py with a FAKE AppKit (the real one only exists on a Mac)."""

import sys
import unittest
from types import SimpleNamespace
from unittest import mock

import support  # noqa: F401
from mymenubar import DEFAULT_ENTRIES, MenuBar, load_appkit


def fake_appkit():
    log = SimpleNamespace(policy=None, removed=[], items=[])

    class NSObject:
        @classmethod
        def alloc(cls):
            return cls()

        def init(self):
            return self

    class Button:
        title = None

        def setTitle_(self, title):
            self.title = title

    class StatusItem:
        def __init__(self):
            self._button, self.menu = Button(), None

        def button(self):
            return self._button

        def setMenu_(self, menu):
            self.menu = menu

    class Bar:
        def statusItemWithLength_(self, length):
            item = StatusItem()
            log.items.append(item)
            return item

        def removeStatusItem_(self, item):
            log.removed.append(item)

    class NSStatusBar:
        @staticmethod
        def systemStatusBar():
            return Bar()

    class NSMenu:
        @classmethod
        def alloc(cls):
            return cls()

        def init(self):
            self.entries = []
            return self

        def addItem_(self, entry):
            self.entries.append(entry)

    class NSMenuItem:
        @classmethod
        def alloc(cls):
            return cls()

        def initWithTitle_action_keyEquivalent_(self, title, action, key):
            self.title, self.action, self.key = title, action, key
            return self

        def setTarget_(self, target):
            self.target = target

        def setRepresentedObject_(self, value):
            self.value = value

        def representedObject(self):
            return self.value

    class NSApplication:
        @staticmethod
        def sharedApplication():
            return SimpleNamespace(setActivationPolicy_=lambda p: setattr(log, "policy", p))

    ns = SimpleNamespace(
        objc=SimpleNamespace(super=super),
        NSApplication=NSApplication, NSMenu=NSMenu, NSMenuItem=NSMenuItem, NSObject=NSObject,
        NSStatusBar=NSStatusBar, NSVariableStatusItemLength=-1,
    )
    return ns, log


class Menu(unittest.TestCase):
    def setUp(self):
        self.ns, self.log = fake_appkit()
        self.chosen = []
        self.bar = MenuBar("⌘", self.chosen.append, appkit=self.ns)

    def test_creates_an_icon_with_the_title_and_the_menu(self):
        self.bar.start()
        item = self.log.items[0]
        self.assertEqual(item.button().title, "⌘")
        self.assertEqual([e.title for e in item.menu.entries], [text for text, _ in DEFAULT_ENTRIES])
        self.assertEqual({e.action for e in item.menu.entries}, {"chosen:"})

    def test_choosing_an_entry_calls_back_with_its_word(self):
        self.bar.start()
        entries = self.log.items[0].menu.entries
        for entry in entries:
            entry.target.chosen_(entry)  # what macOS does when you click
        self.assertEqual(self.chosen, ["toggle", "quit"])

    def test_dock_icon_is_kept_by_default_and_hidden_on_request(self):
        self.bar.start()
        self.assertIsNone(self.log.policy)
        ns, log = fake_appkit()
        MenuBar("⌘", print, hide_dock=True, appkit=ns).start()
        self.assertEqual(log.policy, 1)

    def test_stop_removes_the_icon_once(self):
        self.bar.start()
        self.bar.stop()
        self.bar.stop()
        self.assertEqual(len(self.log.removed), 1)

    def test_stop_before_start_is_harmless(self):
        self.bar.stop()

    def test_custom_entries(self):
        bar = MenuBar("x", self.chosen.append, entries=(("Only", "one"),), appkit=self.ns)
        bar.start()
        self.assertEqual([e.title for e in self.log.items[0].menu.entries], ["Only"])


class Loading(unittest.TestCase):
    def test_missing_pyobjc_gives_the_fix(self):
        with mock.patch.dict(sys.modules, {"objc": None}):  # None makes "import objc" fail
            with self.assertRaises(RuntimeError) as ctx:
                load_appkit()
        self.assertIn("pyobjc-framework-Cocoa", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
