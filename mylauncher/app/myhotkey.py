"""
myhotkey.py - the global hotkey (the key combination that works in ANY application).

We use the pynput library only to LISTEN: it calls us for every key pressed and released, in any
application, from its own background thread (macOS asks for a permission for that, see
docs/01-installation.md, "Permissions"). Recognising the combination is done here, by us:

  * normalise(): a pynput key -> our vocabulary ("command", "shift", "option", "control" or a letter).
  * HotkeyMatcher: remembers which modifiers are held down and says "hotkey!" when the right key is
    pressed with EXACTLY the right modifiers. No pynput inside, so it is tested without a keyboard.
  * HotkeyListener: connects pynput's listener to the matcher. pynput is imported only when we
    start, so the rest of the program (and the tests) work even if it is not installed.

Why not pynput's ready-made GlobalHotKeys? On a real Mac, `--keys` showed that the keys arrived
(`cmd`, then `'d'`) but `--hotkey-test` (which used GlobalHotKeys) printed nothing. Our own matcher is ~25 lines, easy to read, and
uses exactly the events that `--keys` proves are delivered.

IMPORTANT, a limitation: we LISTEN to the key but do not swallow it. The application you are using
at that moment also receives Command+D (Finder: "Duplicate", Terminal: split pane...). If that
bothers you, change hotkey.key / hotkey.modifiers in conf/myconfiguration.json.
"""

from __future__ import annotations

import ctypes
import sys

# pynput names the modifier keys cmd, cmd_r, shift, shift_r, alt, alt_r, alt_gr, ctrl, ctrl_r...
# We only care about which KIND it is: the prefix before "_".
MODIFIER_KINDS = {"cmd": "command", "shift": "shift", "alt": "option", "alt_gr": "option", "ctrl": "control"}


def describe(modifiers, key: str) -> str:
    """("command",), "d" -> "command+d" (for messages to the user)."""
    return "+".join([*modifiers, key])


def normalise(key):
    """A pynput key -> ("modifier", "command") | ("key", "d") | None for keys we do not care about."""
    name = getattr(key, "name", None)  # special keys (Key.cmd, Key.tab...) have a name, letters do not
    if name:
        kind = MODIFIER_KINDS.get(name) or MODIFIER_KINDS.get(name.split("_")[0])
        return ("modifier", kind) if kind else None
    char = getattr(key, "char", None)
    return ("key", char.lower()) if char else None


class HotkeyMatcher:
    """Feed it every press and release; it calls `callback` when the hotkey is pressed."""

    def __init__(self, modifiers, key: str, callback):
        self.modifiers, self.key, self.callback = frozenset(modifiers), key.lower(), callback
        self.held = set()  # modifiers currently down
        self.armed = True  # False while the key is still down: holding "d" repeats presses, we fire once

    def press(self, raw_key) -> None:
        kind = normalise(raw_key)
        if kind is None:
            return
        what, value = kind
        if what == "modifier":
            self.held.add(value)
        elif value == self.key and self.held == self.modifiers:
            self.trigger()

    def trigger(self) -> bool:
        """Call the callback once per physical key press (two sources may report the same press:
        pynput's normal callbacks and the intercept below, so both come through here)."""
        if not self.armed:
            return False
        self.armed = False
        self.callback()
        return True

    def release(self, raw_key) -> None:
        kind = normalise(raw_key)
        if kind is None:
            return
        what, value = kind
        if what == "modifier":
            self.held.discard(value)
        elif value == self.key:
            self.armed = True


# Quartz event numbers and modifier masks (CGEventTypes.h): written as numbers so no import is needed here.
KEY_DOWN, KEY_UP = 10, 11
FLAG_MASKS = {"command": 0x100000, "shift": 0x20000, "option": 0x80000, "control": 0x40000}


def quartz_reader(event):
    """A Quartz keyboard event -> (set of modifiers, lower-case character, is_autorepeat).

    Imported inside the function: Quartz exists only on a Mac (pynput itself installs it there).
    """
    import Quartz

    flags = Quartz.CGEventGetFlags(event)
    modifiers = {name for name, mask in FLAG_MASKS.items() if flags & mask}
    _, text = Quartz.CGEventKeyboardGetUnicodeString(event, 10, None, None)
    repeat = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventAutorepeat)
    return modifiers, (text or "").lower(), bool(repeat)


class HotkeyListener:
    """Starts pynput and feeds the HotkeyMatcher.

    swallow=True: the hotkey is ALSO taken away from the application in front. Without it, Command+D
    reaches Ghostty as well and Ghostty splits/opens a tab. pynput can do this with its
    `darwin_intercept` argument: a function that sees every keyboard event before the applications
    do, and returns None to throw one away. `self.swallowing` tells whether it worked.
    """

    def __init__(self, modifiers, key, callback, factory=None, swallow=False, reader=quartz_reader):
        self.matcher = HotkeyMatcher(modifiers, key, callback)  # callback runs in pynput's thread!
        self._factory = factory  # tests give a fake; normally None = the real pynput
        self._listener = None
        self._swallow = swallow
        self._reader = reader
        self._swallowed_down = False  # we threw the key-down away, so we throw the matching key-up away too
        self.swallowing = False

    def intercept(self, event_type, event):
        """pynput calls this for every key event. Return the event to let it through, None to swallow it.

        Whatever goes wrong here, the event is let through: a bug must never take the keyboard away.
        """
        try:
            if event_type not in (KEY_DOWN, KEY_UP):
                return event
            modifiers, char, repeat = self._reader(event)
            is_ours = char == self.matcher.key and modifiers == self.matcher.modifiers
            if event_type == KEY_DOWN and is_ours:
                if not repeat:
                    self.matcher.trigger()
                self._swallowed_down = True
                return None
            if event_type == KEY_UP and char == self.matcher.key and self._swallowed_down:
                self._swallowed_down = False
                self.matcher.armed = True
                return None
        except Exception:  # noqa: BLE001
            return event
        return event

    def start(self) -> None:
        factory = self._factory
        if factory is None:
            try:
                from pynput import keyboard
            except ImportError:
                raise RuntimeError("pynput is not installed: run  pip install pynput  (see docs/01-installation.md)") from None
            factory = keyboard.Listener
        callbacks = dict(on_press=self.matcher.press, on_release=self.matcher.release)
        if self._swallow:
            try:
                self._listener = factory(**callbacks, darwin_intercept=self.intercept)
                self.swallowing = True
            except TypeError:  # an old pynput that does not know darwin_intercept
                self._listener = factory(**callbacks)
        else:
            self._listener = factory(**callbacks)
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None


# --------------------------------------------------------------------------- #
# Diagnostics: "why does my hotkey do nothing?"                               #
# --------------------------------------------------------------------------- #

FRAMEWORKS = "/System/Library/Frameworks/{0}.framework/{0}"


def _accessibility_trusted() -> bool:
    """macOS function AXIsProcessTrusted(): may this process control/observe the keyboard?"""
    lib = ctypes.cdll.LoadLibrary(FRAMEWORKS.format("ApplicationServices"))
    lib.AXIsProcessTrusted.restype = ctypes.c_bool
    return bool(lib.AXIsProcessTrusted())


def _input_monitoring() -> int:
    """macOS function IOHIDCheckAccess(listen): 0 = granted, 1 = denied, 2 = never asked."""
    lib = ctypes.cdll.LoadLibrary(FRAMEWORKS.format("IOKit"))
    lib.IOHIDCheckAccess.restype = ctypes.c_uint32
    lib.IOHIDCheckAccess.argtypes = [ctypes.c_uint32]
    return int(lib.IOHIDCheckAccess(1))  # 1 = kIOHIDRequestTypeListenEvent


def permission_report(platform: str = sys.platform, accessibility=_accessibility_trusted, monitoring=_input_monitoring) -> list:
    """Ask macOS about the two permissions. Returns [(symbol, text), ...]; empty when not on a Mac.

    Best effort: if macOS does not answer (a different version, say) we say "unknown" instead of failing.
    """
    if platform != "darwin":
        return []
    report = []
    try:
        ok = accessibility()
        report.append(("✔" if ok else "✘", "Accessibility / device control: " + ("granted" if ok else "NOT granted to this program")))
    except Exception:  # noqa: BLE001 - diagnostics must never crash
        report.append(("!", "Accessibility: could not check"))
    try:
        state = monitoring()
        text = {0: "granted", 1: "NOT granted (denied)", 2: "not asked yet"}.get(state, f"unknown answer {state}")
        report.append(("✔" if state == 0 else "✘", "Input Monitoring: " + text))
    except Exception:  # noqa: BLE001
        report.append(("!", "Input Monitoring: could not check"))
    return report


def watch_keys(printer=print, factory=None):
    """Start printing EVERY key pynput sees. Returns the running listener (call .join() to wait).

    If you press keys and nothing is printed, macOS is not letting this program see the keyboard (permissions).
    If keys are printed but the hotkey does nothing, the combination in the JSON is the problem.
    """
    if factory is None:
        try:
            from pynput import keyboard
        except ImportError:
            raise RuntimeError("pynput is not installed: run  pip install pynput  (see docs/01-installation.md)") from None
        factory = keyboard.Listener
    listener = factory(on_press=lambda key: printer(f"pressed   {key!r}"), on_release=lambda key: printer(f"released  {key!r}"))
    listener.start()
    return listener
