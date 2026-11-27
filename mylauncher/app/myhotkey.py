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

GUIDED TOUR (for someone who is just starting to program) ---------------------------------------------------------------
READ THIS FIRST - the file grew by layers, and the text ABOVE describes the first layer. History, honestly:
  v1  pynput's Listener + our own HotkeyMatcher (the text above).
  v2  swallow=True: a `darwin_intercept` function that can throw a key away so the application in front does NOT also get Command+D.
  v3  (today, the default) QuartzTap: our OWN keyboard listener built directly on macOS's event tap, with NO pynput in the normal path, because pynput's
      Listener decodes keys with an API macOS only allows on the main thread and on recent macOS that crashed Python. pynput is still used by `--keys`
      (watch_keys) and by the tests through the `factory` argument. The "limitation: we do not swallow the key" paragraph is therefore OLD: with
      hotkey.swallow = true the key IS swallowed.
So the file has FIVE parts, bottom to top:
  1. VOCABULARY       MODIFIER_KINDS, describe, normalise       pynput key objects -> our words ("command", "d").
  2. THE MATCHER      HotkeyMatcher (press / release / trigger)  pure logic, no keyboard, no Mac: "is the hotkey pressed NOW, exactly once?"
  3. THE EVENT TAP    quartz_reader, hid_key_age, TAP_DISABLED, QuartzTap     the macOS plumbing (Quartz), in its own thread.
  4. THE LISTENER     HotkeyListener (intercept, start, stop, healthy, starved, guard, restart)   glue + SELF-REPAIR.
  5. DIAGNOSTICS      permission_report, watch_keys             "why does my hotkey do nothing?".

THE MATCHER IN WORDS. `held` is the set of modifiers currently down. On a key press: a modifier is ADDED to `held`; the hotkey letter with held == the wanted
modifiers EXACTLY (==, not "contains": Command+Shift+D must not fire Command+D) calls trigger(). `armed` prevents repeats: holding D sends many presses, we want
ONE. It is re-armed on key-up, or after 0.6 s of silence (a lost key-up must not disable the hotkey forever). time.monotonic() is a clock that never goes backwards
(unlike the wall clock), the right one for measuring "how long since".
WHAT IS AN EVENT TAP? macOS lets a program register a function that sees every keyboard event BEFORE the applications do. Returning the event lets it through;
returning None throws it away (swallow). It runs in a thread with its own "run loop" (an event loop like Tk's mainloop, owned by macOS: CFRunLoopRun).
macOS switches a tap OFF if its function is too slow ("tap disabled" events); then the hotkey silently dies. So HotkeyListener WATCHES itself: healthy() checks
that the thread lives, that no "disabled" event came, and (starved) that the keyboard hardware did not see a key that OUR tap missed. A guard thread restarts it.
Try it:   python3 -c "import sys; sys.path.insert(0,'app'); from myhotkey import *; m=HotkeyMatcher(['command'],'d',lambda: print('FIRED')); import types as t; K=lambda n: t.SimpleNamespace(name=n); C=lambda c: t.SimpleNamespace(char=c, name=None); m.press(K('cmd')); m.press(C('d')); m.press(C('d')); m.release(C('d')); m.press(C('d'))"
          (prints FIRED twice: the repeat in the middle is ignored, the press after the release fires again)
"""

from __future__ import annotations

import ctypes
import sys
import time

# pynput names the modifier keys cmd, cmd_r, shift, shift_r, alt, alt_r, alt_gr, ctrl, ctrl_r...
# We only care about which KIND it is: the prefix before "_".
# A dict of "which pynput names mean which of our four words". "alt" is the Option key on a Mac, and alt_gr is the right Option: both are "option".
MODIFIER_KINDS = {"cmd": "command", "shift": "shift", "alt": "option", "alt_gr": "option", "ctrl": "control"}


def describe(modifiers, key: str) -> str:
    """("command",), "d" -> "command+d" (for messages to the user)."""
    return "+".join([*modifiers, key])


def normalise(key):
    """A pynput key -> ("modifier", "command") | ("key", "d") | None for keys we do not care about."""
    # getattr(obj, "name", None) reads an attribute that may not exist, giving None instead of an error: a pynput `Key.cmd` has .name, a letter has .char.
    # `.get(name) or .get(name.split("_")[0])`: try the full name ("cmd_r"), else the part before "_" ("cmd"): left and right keys are the same kind.
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
        # frozenset = a set that cannot change; set operations make the rule short: `self.held == self.modifiers` compares two sets, order never matters.
        self.held = set()  # modifiers currently down
        self.armed = True  # False while the key is still down: holding "d" repeats presses, we fire once
        self.last_attempt = 0.0  # when the key was last seen down; if its key-up was lost we do not stay disarmed for ever

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
        now = time.monotonic()
        if not self.armed and now - self.last_attempt < 0.6:  # still held down (repeat), or a real double press
            self.last_attempt = now
            return False
        self.last_attempt = now
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
# These are Apple's numbers for "a key went down / up" and for each modifier's bit in the event's FLAGS number. `flags & mask` ("bitwise AND") is non-zero
# exactly when that bit is set: that is how several yes/no facts are packed into one integer. The set comprehension in quartz_reader unpacks them.
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


def hid_key_age() -> float:
    """Seconds since the last key press that the keyboard hardware reported (whatever application got it)."""
    import Quartz

    return float(Quartz.CGEventSourceSecondsSinceLastEventType(Quartz.kCGEventSourceStateHIDSystemState, Quartz.kCGEventKeyDown))


# macOS switches an event tap OFF when its callback is too slow (a flood of key events, e.g. Espanso typing a long text)
# and tells the callback with one of these two "event types". pynput does not switch it on again, so we notice and restart.
TAP_DISABLED = (0xFFFFFFFE, 0xFFFFFFFF, -2, -1)  # by timeout, by user input (signed or unsigned, depending on the binding)


class QuartzTap:
    """Our OWN keyboard listener: one Quartz event tap, no pynput.

    Why: pynput's Listener decodes every key with a text-input API that macOS only allows on the main
    thread; on recent macOS that kills Python ("Python quit unexpectedly", pynput issues #424 and #510).
    This tap asks only for keyDown and keyUp, and reads the character through `quartz_reader` inside
    `intercept` (which never raises). Same small interface as pynput's listener: start, stop, is_alive.
    """

    def __init__(self, intercept, listen_only=False):
        self._intercept = intercept
        self._listen_only = listen_only
        self._tap = None
        self._loop = None
        self._thread = None
        self._ready = None
        self._stopped = False

    def start(self) -> None:
        import threading

        # Step 20.15: check for Quartz HERE, in the calling thread, BEFORE starting the tap thread. Seen on a real Mac: started with Homebrew's own python (no PyObjC),
        # the thread died with "No module named 'Quartz'", start() then reported the MISLEADING "permission?" message, and the watchdog retried every 2 seconds for ever.
        # Now the missing library is named, and the fix is told: use the project's virtual environment (mlapp does).
        try:
            import Quartz  # noqa: F401
        except ImportError:
            raise RuntimeError(f"PyObjC (Quartz) is not installed for this Python ({sys.executable}). Start the launcher with the project's virtual environment: "
                               "`mlapp` or `.venv/bin/python app/mylauncher_app.py` (create it with setup.sh), or run: .venv/bin/pip install -r app/requirements.txt") from None
        # threading.Event is a flag one thread can WAIT on until another sets it: start() waits up to 5 s for the new thread to say "the tap exists (or failed)".
        # daemon=True means this thread does not keep the program alive when everything else has finished.
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="hotkey-tap", daemon=True)
        self._thread.start()
        self._ready.wait(5)
        if self._tap is None:
            raise RuntimeError("macOS did not create the keyboard tap (Accessibility / Input Monitoring permission?)")

    def _run(self) -> None:
        try:
            import Quartz

            # A CALLBACK again: macOS calls `callback` for every event. `mine` is a dict used as a box (chapter 14) so the callback can see the tap's port without
            # reading self._tap, which stop() may have cleared. The comment below records a REAL crash this once caused: a NULL port is a segmentation fault.
            mine = {}  # this tap's own port. NEVER read self._tap in the callback: stop() may have cleared it
            # and CGEventTapEnable(None, ...) is a segmentation fault (crash report 2026-11-17 12:28).

            def callback(proxy, event_type, event, refcon):
                if self._stopped:
                    return event
                if event_type in TAP_DISABLED:
                    self._intercept(event_type, event)
                    port = mine.get("port")
                    if port is not None:
                        Quartz.CGEventTapEnable(port, True)  # switch it on again at once
                    return event
                return self._intercept(event_type, event)

            mask = (1 << KEY_DOWN) | (1 << KEY_UP)
            option = Quartz.kCGEventTapOptionListenOnly if self._listen_only else Quartz.kCGEventTapOptionDefault
            self._tap = Quartz.CGEventTapCreate(Quartz.kCGSessionEventTap, Quartz.kCGHeadInsertEventTap, option, mask, callback, None)
            if self._tap is None:
                return
            mine["port"] = self._tap
            source = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
            self._loop = Quartz.CFRunLoopGetCurrent()
            Quartz.CFRunLoopAddSource(self._loop, source, Quartz.kCFRunLoopCommonModes)
            Quartz.CGEventTapEnable(self._tap, True)
            self._ready.set()
            Quartz.CFRunLoopRun()
        finally:
            self._ready.set()

    def is_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def stop(self) -> None:
        try:
            import Quartz

            self._stopped = True  # first: the callback lets every event through from now on
            if self._tap is not None:
                Quartz.CGEventTapEnable(self._tap, False)
                Quartz.CFMachPortInvalidate(self._tap)
            if self._loop is not None:
                Quartz.CFRunLoopStop(self._loop)
        except Exception as exc:  # noqa: BLE001 - stopping must never raise
            print(f"[hotkey] stop: {type(exc).__name__}: {exc}", flush=True)

    def join(self) -> None:
        if self._thread:
            self._thread.join()


class HotkeyListener:
    """Starts pynput and feeds the HotkeyMatcher.

    swallow=True: the hotkey is ALSO taken away from the application in front. Without it, Command+D
    reaches Ghostty as well and Ghostty splits/opens a tab. pynput can do this with its
    `darwin_intercept` argument: a function that sees every keyboard event before the applications
    do, and returns None to throw one away. `self.swallowing` tells whether it worked.
    """

    def __init__(self, modifiers, key, callback, factory=None, swallow=False, reader=quartz_reader, key_age=hid_key_age):
        self.matcher = HotkeyMatcher(modifiers, key, callback)  # callback runs in pynput's thread!
        self._factory = factory  # tests give a fake; normally None = the real pynput
        self._listener = None
        self._swallow = swallow
        self._reader = reader
        self._swallowed_down = False  # we threw the key-down away, so we throw the matching key-up away too
        self.swallowing = False
        self.tap_disabled = False  # macOS switched the tap off: see healthy()
        self._key_age = key_age  # how long ago the hardware saw a key (replaced in tests)
        self.last_seen = time.monotonic()  # when OUR tap last saw a key event
        self.last_restart = 0.0

    def healthy(self) -> bool:
        """False when the hotkey cannot work any more (tap switched off, or pynput's thread ended)."""
        if self._listener is None:
            return True  # never started (no permission...): nothing to repair
        alive = getattr(self._listener, "is_alive", lambda: True)()
        # `and` chains three conditions; Python stops at the first false one. getattr(..., lambda: True)() is "call is_alive if it exists, else assume alive".
        return alive and not self.tap_disabled and not self.starved()

    def starved(self) -> bool:
        """True when the keyboard had a key press that OUR tap never saw: the tap is silently dead.

        (The log of a real Mac showed it: after an action no "[hotkey] pressed" any more, and no "tap disabled" event either.)
        """
        try:
            hardware = self._key_age()
        except Exception:  # noqa: BLE001 - cannot ask (no Quartz): assume all is well
            return False
        # hardware = seconds since the keyboard last reported a key to ANYONE; ours = seconds since OUR tap last saw one. If the hardware key is MORE RECENT than
        # ours by over a second, a key was pressed that we never saw: our tap is dead without telling us. (+1.0 is a tolerance against tiny timing differences.)
        ours = time.monotonic() - self.last_seen
        return hardware + 1.0 < ours

    def guard(self, log=print, every: float = 1.5, minimum_gap: float = 10.0):
        """A background thread (no Tk): every `every` seconds, if the hotkey is not healthy, start a new listener."""
        import threading

        # A WATCHER THREAD. `loop` runs forever in its own thread: sleep, check, repair if needed, `continue` (= skip to the next lap). minimum_gap stops it
        # from restarting every 1.5 s if restarting does not help. Its try/except means the guard itself can never die; it logs and tries again.
        def loop():
            while True:
                time.sleep(every)
                try:
                    if self._listener is None or self.healthy() or time.monotonic() - self.last_restart < minimum_gap:
                        continue
                    log(f"[guard] the keyboard listener is dead (tap_disabled={self.tap_disabled}); starting a new one")
                    self.last_restart = time.monotonic()
                    self.restart()
                except Exception as exc:  # noqa: BLE001 - the guard itself must never die
                    log(f"[guard] restart failed: {exc}")

        thread = threading.Thread(target=loop, name="hotkey-guard", daemon=True)
        thread.start()
        return thread

    def restart(self) -> None:
        """Throw the old listener away and start a new one (a new event tap)."""
        try:
            self.stop()
        except Exception:  # noqa: BLE001 - a dead listener may complain when stopped
            self._listener = None
        self.tap_disabled = False
        self._swallowed_down = False
        self.matcher.armed = True
        self.last_seen = time.monotonic()
        self.start()

    def intercept(self, event_type, event):
        """The tap calls this for every key event. Return the event to let it through, None to swallow it.

        Whatever goes wrong here, the event is let through: a bug must never take the keyboard away.
        """
        self.last_seen = time.monotonic()
        try:
            # THE RULE OF THIS FUNCTION: return `event` (let it through) in EVERY doubtful case. Only a confirmed hotkey press is thrown away (return None).
            # On key-down of OUR combination: fire the callback once (not for an auto-repeat) and swallow it; remember that (_swallowed_down) so the matching
            # key-UP is swallowed too (an application that sees an "up" without a "down" can misbehave).
            if event_type in TAP_DISABLED:
                self.tap_disabled = True
                return event
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
            self._listener = QuartzTap(self.intercept, listen_only=not self._swallow)
            self.swallowing = self._swallow
            try:
                self._listener.start()
            except Exception:
                # A listener that never started is NOT "dead and to be repaired": forget it, so healthy() says "nothing to repair" (see its first line) and the
                # watchdog and the guard do not retry every few seconds for ever. The caller reports the problem once.
                self._listener = None
                self.swallowing = False
                raise
            return
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


# ctypes (standard library) calls functions of macOS's own C libraries directly: LoadLibrary opens the framework file, `restype` / `argtypes` tell Python what
# the C function returns and takes (otherwise it guesses wrongly). This is how we ask macOS "do I have permission?" without installing anything.
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
    # `accessibility` and `monitoring` are parameters (functions), so a test passes fakes that return 0/1/2 and no Mac is needed. Each check has its own
    # try/except: a diagnostic must never crash, and one failing check must not hide the other.
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
