"""
myhotkey.py - the global hotkey (the key combination that works in ANY application).

We use the pynput library. It listens to the keyboard in its own background thread, and for that
macOS requires a permission (see docs/01-installation.md, "Permissions").

Two parts:
  * to_pynput(): turns the settings of the JSON file into pynput's notation. Pure function, tested.
  * HotkeyListener: starts and stops the listening. pynput is imported only when we start, so the
    rest of the program (and the tests) work even if pynput is not installed.

IMPORTANT, a limitation of pynput: it LISTENS to the key but does not swallow it. The application
you are using at that moment also receives Command+D (Finder: "Duplicate", Terminal: split pane...).
If that bothers you, change hotkey.key / hotkey.modifiers in conf/myconfiguration.json.
"""

from __future__ import annotations

# our word (as written in the JSON)  ->  pynput's word
PYNPUT_NAMES = {"command": "<cmd>", "shift": "<shift>", "option": "<alt>", "control": "<ctrl>"}


def to_pynput(modifiers, key: str) -> str:
    """("command", "shift"), "d"  ->  "<cmd>+<shift>+d" """
    return "+".join([*(PYNPUT_NAMES[m] for m in modifiers), key])


def describe(modifiers, key: str) -> str:
    """("command",), "d" -> "command+d" (for messages to the user)."""
    return "+".join([*modifiers, key])


class HotkeyListener:
    def __init__(self, modifiers, key, callback, factory=None):
        self.combination = to_pynput(modifiers, key)
        self.callback = callback  # called (in pynput's thread!) every time the keys are pressed
        self._factory = factory  # tests give a fake; normally None = the real pynput
        self._listener = None

    def start(self) -> None:
        factory = self._factory
        if factory is None:
            try:
                from pynput import keyboard
            except ImportError:
                raise RuntimeError("pynput is not installed: run  pip install pynput  (see docs/01-installation.md)") from None
            factory = keyboard.GlobalHotKeys
        self._listener = factory({self.combination: self.callback})
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
