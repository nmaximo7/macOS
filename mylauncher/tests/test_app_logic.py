"""app/: everything of the window that does NOT need a screen (state, engine client, hotkey)."""

import json
import subprocess
import unittest
from types import SimpleNamespace

import support  # noqa: F401  (puts cli/ and app/ on the import path)
from myengine import Engine, EngineError, RunResult
from myhotkey import HotkeyListener, HotkeyMatcher, describe, normalise, permission_report, watch_keys
from mystate import LauncherState

ANSWER = {
    "query": "s",
    "completion": "shutdown",
    "results": [{"id": "cmd:shutdown", "title": "Shutdown", "confirm": True}, {"id": "app:Safari", "title": "Run Safari", "confirm": False}],
}


class State(unittest.TestCase):
    def setUp(self):
        self.state = LauncherState()
        self.state.set_answer(ANSWER)

    def test_starts_on_the_best_match(self):
        self.assertEqual(self.state.current["id"], "cmd:shutdown")

    def test_move_wraps_around(self):
        self.state.move(+1)
        self.assertEqual(self.state.current["id"], "app:Safari")
        self.state.move(+1)
        self.assertEqual(self.state.selected, 0)
        self.state.move(-1)
        self.assertEqual(self.state.selected, 1)

    def test_new_answer_resets_the_selection(self):
        self.state.move(+1)
        self.state.set_answer(ANSWER)
        self.assertEqual(self.state.selected, 0)

    def test_empty_state_is_safe(self):
        self.state.clear()
        self.state.move(+1)
        self.assertIsNone(self.state.current)

    def test_tab_text(self):
        self.assertEqual(self.state.tab_text("s"), "shutdown")
        self.state.clear()
        self.assertEqual(self.state.tab_text("qqq"), "qqq")


class FakeProcess:
    """Remembers the command it was given and answers with prepared output."""

    def __init__(self, stdout="", stderr="", error=None):
        self.calls, self.stdout, self.stderr, self.error = [], stdout, stderr, error

    def __call__(self, command, **kwargs):
        self.calls.append(command)
        if self.error:
            raise self.error
        return SimpleNamespace(stdout=self.stdout, stderr=self.stderr, returncode=0)


class EngineClient(unittest.TestCase):
    def engine(self, process, config=None):
        return Engine(config_path=config, runner=process, python="PY", script="SCRIPT")

    def test_search_builds_the_command_and_reads_json(self):
        process = FakeProcess(json.dumps(ANSWER))
        answer = self.engine(process, config="/c.json").search("obs")
        self.assertEqual(process.calls[0], ["PY", "SCRIPT", "search", "--json", "--config", "/c.json", "--", "obs"])
        self.assertEqual(answer["completion"], "shutdown")

    def test_option_looking_text_stays_text(self):
        process = FakeProcess(json.dumps(ANSWER))
        self.engine(process).search("--help")
        self.assertEqual(process.calls[0][-2:], ["--", "--help"])

    def test_empty_text_searches_everything(self):
        process = FakeProcess(json.dumps(ANSWER))
        self.engine(process).search("   ")
        self.assertEqual(process.calls[0], ["PY", "SCRIPT", "search", "--json"])

    def test_engine_error_is_reported(self):
        with self.assertRaises(EngineError):
            self.engine(FakeProcess(json.dumps({"error": "bad config"}))).search("x")

    def test_garbage_output(self):
        with self.assertRaises(EngineError) as ctx:
            self.engine(FakeProcess("Traceback...", stderr="ValueError: boom")).search("x")
        self.assertIn("boom", str(ctx.exception))

    def test_cannot_start_or_too_slow(self):
        for error in (FileNotFoundError("PY"), subprocess.TimeoutExpired("PY", 15)):
            with self.subTest(error=type(error).__name__), self.assertRaises(EngineError):
                self.engine(FakeProcess(error=error)).search("x")

    def test_run_always_passes_yes_and_id(self):
        process = FakeProcess(json.dumps({"item": {}, "result": {"ok": True, "message": "done"}}))
        self.assertEqual(self.engine(process).run("app:Safari"), RunResult(True, "done", False))
        self.assertEqual(process.calls[0], ["PY", "SCRIPT", "run", "--json", "--id", "app:Safari", "--yes"])

    def test_run_passes_the_typed_text_and_force(self):
        process = FakeProcess(json.dumps({"item": {}, "result": {"ok": True, "message": "done"}}))
        self.engine(process).run("link:yt", "yt -lofi", force=True)
        # "--text=..." is ONE argument, so text that starts with "-" cannot be mistaken for an option.
        self.assertEqual(process.calls[0][3:], ["--json", "--id", "link:yt", "--yes", "--text=yt -lofi", "--force"])

    def test_run_failure_and_needs_force(self):
        self.assertEqual(self.engine(FakeProcess(json.dumps({"error": "no item"}))).run("x"), RunResult(False, "no item"))
        answer = {"item": {}, "result": {"ok": False, "message": "frozen", "needs_force": True}}
        self.assertEqual(self.engine(FakeProcess(json.dumps(answer))).run("kill:X", "kill x"), RunResult(False, "frozen", True))


class Key:
    """A fake pynput key: special keys have a .name (Key.cmd), letters have a .char."""

    def __init__(self, name=None, char=None):
        self.name, self.char = name, char


CMD, CMD_R, SHIFT, ALT, TAB = Key("cmd"), Key("cmd_r"), Key("shift"), Key("alt"), Key("tab")
D, UPPER_D = Key(char="d"), Key(char="D")


class Hotkey(unittest.TestCase):
    def matcher(self, modifiers=("command",), key="d"):
        self.fired = []
        return HotkeyMatcher(modifiers, key, lambda: self.fired.append(1))

    def test_describe(self):
        self.assertEqual(describe(("command",), "d"), "command+d")

    def test_normalise(self):
        self.assertEqual(normalise(CMD), ("modifier", "command"))
        self.assertEqual(normalise(CMD_R), ("modifier", "command"))  # right Command counts too
        self.assertEqual(normalise(Key("alt_gr")), ("modifier", "option"))
        self.assertEqual(normalise(Key("ctrl_l")), ("modifier", "control"))
        self.assertEqual(normalise(UPPER_D), ("key", "d"))
        self.assertIsNone(normalise(TAB))
        self.assertIsNone(normalise(Key()))

    def test_fires_on_the_combination(self):
        m = self.matcher()
        m.press(CMD)
        m.press(D)
        self.assertEqual(self.fired, [1])

    def test_the_exact_sequence_seen_on_the_real_mac(self):
        # --keys printed: cmd pressed, d pressed, cmd released, d released
        m = self.matcher()
        for action, key in (("p", CMD), ("p", D), ("r", CMD), ("r", D)):
            (m.press if action == "p" else m.release)(key)
        self.assertEqual(self.fired, [1])

    def test_the_letter_alone_does_nothing(self):
        m = self.matcher()
        m.press(D)
        self.assertEqual(self.fired, [])

    def test_extra_modifiers_do_not_fire(self):
        m = self.matcher()
        m.press(CMD)
        m.press(SHIFT)
        m.press(UPPER_D)  # Command+Shift+D is another shortcut
        self.assertEqual(self.fired, [])

    def test_several_modifiers_in_any_order(self):
        m = self.matcher(("command", "shift"))
        m.press(SHIFT)
        m.press(CMD)
        m.press(UPPER_D)
        self.assertEqual(self.fired, [1])

    def test_holding_the_key_fires_once_and_again_after_release(self):
        m = self.matcher()
        m.press(CMD)
        m.press(D)
        m.press(D)  # auto-repeat
        self.assertEqual(self.fired, [1])
        m.release(D)
        m.press(D)  # pressed again, Command still down
        self.assertEqual(self.fired, [1, 1])

    def test_releasing_the_modifier_disarms(self):
        m = self.matcher()
        m.press(CMD)
        m.release(CMD)
        m.press(D)
        self.assertEqual(self.fired, [])

    def test_unrelated_keys_are_ignored(self):
        m = self.matcher()
        m.press(CMD)
        m.press(TAB)  # Command+Tab: switching apps
        m.release(TAB)
        self.assertEqual(self.fired, [])

    def test_listener_connects_pynput_to_the_matcher_and_stops(self):
        made = {}

        class FakeListener:
            def __init__(self, on_press, on_release):
                made["press"], made["release"], made["obj"] = on_press, on_release, self
                self.started = self.stopped = False

            def start(self):
                self.started = True

            def stop(self):
                self.stopped = True

        pressed = []
        listener = HotkeyListener(("command",), "d", lambda: pressed.append(1), factory=FakeListener)
        listener.start()
        self.assertTrue(made["obj"].started)
        made["press"](CMD)
        made["press"](D)  # "type" the keys through pynput's callbacks
        self.assertEqual(pressed, [1])
        listener.stop()
        self.assertTrue(made["obj"].stopped)
        listener.stop()  # stopping twice is harmless

    def test_missing_pynput_gives_a_helpful_error(self):
        import sys
        from unittest import mock

        with mock.patch.dict(sys.modules, {"pynput": None}):  # None makes "import pynput" fail
            with self.assertRaises(RuntimeError) as ctx:
                HotkeyListener(("command",), "d", lambda: None).start()
        self.assertIn("pip install pynput", str(ctx.exception))


class Swallow(unittest.TestCase):
    """The hotkey is taken away from the application in front (so Ghostty does not split/open a tab)."""

    def setUp(self):
        self.fired = []
        self.events = {"down_d": ({"command"}, "d", False), "repeat_d": ({"command"}, "d", True), "up_d": ({"command"}, "d", False),
                       "down_shift_d": ({"command", "shift"}, "d", False), "down_x": ({"command"}, "x", False), "plain_d": (set(), "d", False)}
        self.listener = HotkeyListener(("command",), "d", lambda: self.fired.append(1), swallow=True, reader=lambda event: self.events[event])

    def test_the_hotkey_is_swallowed_and_fires_once(self):
        self.assertIsNone(self.listener.intercept(10, "down_d"))
        self.assertEqual(self.fired, [1])

    def test_autorepeat_is_swallowed_but_does_not_fire_again(self):
        self.listener.intercept(10, "down_d")
        self.assertIsNone(self.listener.intercept(10, "repeat_d"))
        self.assertEqual(self.fired, [1])

    def test_key_up_of_a_swallowed_key_is_swallowed_and_rearms(self):
        self.listener.intercept(10, "down_d")
        self.assertIsNone(self.listener.intercept(11, "up_d"))
        self.listener.intercept(10, "down_d")
        self.assertEqual(self.fired, [1, 1])

    def test_other_keys_pass_through(self):
        for event in ("down_shift_d", "down_x", "plain_d"):  # other modifiers, other key, no modifier
            with self.subTest(event=event):
                self.assertEqual(self.listener.intercept(10, event), event)
        self.assertEqual(self.listener.intercept(11, "plain_d"), "plain_d")  # an unrelated key-up
        self.assertEqual(self.listener.intercept(12, "down_d"), "down_d")  # modifier-change events are never touched
        self.assertEqual(self.fired, [])

    def test_a_bug_in_the_reader_lets_the_event_through(self):
        def boom(event):
            raise ValueError("x")

        listener = HotkeyListener(("command",), "d", lambda: None, swallow=True, reader=boom)
        self.assertEqual(listener.intercept(10, "e"), "e")

    def test_pynput_callbacks_and_intercept_do_not_double_fire(self):
        self.listener.matcher.press(CMD)
        self.listener.intercept(10, "down_d")
        self.listener.matcher.press(D)  # in case pynput reports the same press as well
        self.assertEqual(self.fired, [1])

    def test_start_passes_darwin_intercept_and_reports_it(self):
        seen = {}

        class FakeListener:
            def __init__(self, **kwargs):
                seen.update(kwargs)

            def start(self):
                pass

        self.listener._factory = FakeListener
        self.listener.start()
        self.assertEqual(seen["darwin_intercept"], self.listener.intercept)
        self.assertTrue(self.listener.swallowing)

    def test_old_pynput_without_darwin_intercept_still_works(self):
        class OldListener:
            def __init__(self, on_press, on_release):
                pass

            def start(self):
                pass

        self.listener._factory = OldListener
        self.listener.start()
        self.assertFalse(self.listener.swallowing)

    def test_without_swallow_nothing_is_passed(self):
        seen = {}

        class FakeListener:
            def __init__(self, **kwargs):
                seen.update(kwargs)

            def start(self):
                pass

        HotkeyListener(("command",), "d", lambda: None, factory=FakeListener).start()
        self.assertNotIn("darwin_intercept", seen)


class Diagnostics(unittest.TestCase):
    def test_not_a_mac_reports_nothing(self):
        self.assertEqual(permission_report(platform="linux"), [])

    def test_report_on_a_mac(self):
        report = permission_report("darwin", accessibility=lambda: True, monitoring=lambda: 0)
        self.assertEqual([s for s, _ in report], ["✔", "✔"])
        report = permission_report("darwin", accessibility=lambda: False, monitoring=lambda: 1)
        self.assertEqual([s for s, _ in report], ["✘", "✘"])
        self.assertIn("NOT granted", report[0][1])
        self.assertIn("not asked", permission_report("darwin", lambda: True, lambda: 2)[1][1])

    def test_failing_checks_do_not_crash(self):
        def boom():
            raise OSError("no such framework")

        self.assertEqual([s for s, _ in permission_report("darwin", boom, boom)], ["!", "!"])

    def test_watch_keys_prints_presses_and_releases(self):
        lines = []

        class FakeListener:
            def __init__(self, on_press, on_release):
                self.on_press, self.on_release, self.started = on_press, on_release, False

            def start(self):
                self.started = True

        listener = watch_keys(printer=lines.append, factory=FakeListener)
        self.assertTrue(listener.started)
        listener.on_press("KEY_A")
        listener.on_release("KEY_A")
        self.assertEqual(lines, ["pressed   'KEY_A'", "released  'KEY_A'"])


if __name__ == "__main__":
    unittest.main()


class Scrolling(unittest.TestCase):
    def state(self, count, rows=3):
        state = LauncherState(rows=rows)
        state.set_answer({"results": [{"id": str(i)} for i in range(count)], "mode": "run", "highlight": 3})
        return state

    def test_mode_and_highlight_come_from_the_answer(self):
        state = self.state(1)
        self.assertEqual((state.mode, state.highlight), ("run", 3))
        state.clear()
        self.assertEqual((state.mode, state.highlight), ("normal", 0))

    def test_only_the_rows_that_fit_are_visible(self):
        state = self.state(10)
        self.assertEqual([r["id"] for r in state.visible], ["0", "1", "2"])

    def test_moving_down_scrolls_the_least_possible(self):
        state = self.state(10)
        for _ in range(3):
            state.move(+1)
        self.assertEqual((state.selected, state.top, state.visible_selected), (3, 1, 2))

    def test_moving_up_scrolls_back(self):
        state = self.state(10)
        for _ in range(4):
            state.move(+1)
        for _ in range(4):
            state.move(-1)
        self.assertEqual((state.selected, state.top), (0, 0))

    def test_wrapping_around_scrolls_to_the_end_and_to_the_start(self):
        state = self.state(10)
        state.move(-1)  # from the first to the last
        self.assertEqual((state.selected, state.top), (9, 7))
        state.move(+1)
        self.assertEqual((state.selected, state.top), (0, 0))

    def test_clicking_a_visible_row(self):
        state = self.state(10)
        state.move(+1), state.move(+1), state.move(+1)
        state.select_visible(0)
        self.assertEqual(state.current["id"], "1")
        state.select_visible(99)  # outside: ignored
        self.assertEqual(state.current["id"], "1")


class Theme(unittest.TestCase):
    def test_shorten(self):
        from mytheme import shorten

        self.assertEqual(shorten("short", 10), "short")
        self.assertEqual(shorten("a  long\ntext here", 8), "a long…")
        self.assertEqual(shorten("anything", 1), "")
        self.assertEqual(shorten("", 5), "")

    def test_row_texts_give_the_subtitle_the_room_that_is_left(self):
        from mytheme import row_texts

        icon, title, subtitle, badge = row_texts({"icon": "🚀", "title": "Run X", "subtitle": "z" * 100, "badge": "Application"}, 40)
        self.assertEqual((icon, title, badge), ("🚀", "Run X", "Application"))
        self.assertEqual(len(subtitle), 40 - 5 - 11 - 6)
        self.assertTrue(subtitle.endswith("…"))

    def test_mode_labels(self):
        from mytheme import mode_label

        self.assertEqual(mode_label("kill"), "💀 Close an app")
        self.assertEqual(mode_label("normal"), "")


class Chrome(unittest.TestCase):
    """mychrome.apply_style with a pretend AppKit: we check WHAT it asks Cocoa to do."""

    class Button:
        def __init__(self):
            self.hidden = False

        def setHidden_(self, value):
            self.hidden = value

    class Window:
        def __init__(self, title, buttons):
            self._title, self.buttons, self.calls = title, buttons, []

        def title(self):
            return self._title

        def standardWindowButton_(self, which):
            return self.buttons[which]

        def __getattr__(self, name):
            if name.startswith("set"):
                return lambda value: self.calls.append((name, value))
            raise AttributeError(name)

    def appkit(self, windows):
        class NSColor:
            @staticmethod
            def colorWithSRGBRed_green_blue_alpha_(r, g, b, a):
                return ("color", round(r, 2), round(g, 2), round(b, 2), a)

        class NSApp:
            @staticmethod
            def windows():
                return windows

        return type("FakeAppKit", (), {"NSApp": NSApp, "NSColor": NSColor})

    def test_hides_the_three_buttons_and_the_title(self):
        from mychrome import apply_style

        buttons = [self.Button() for _ in range(3)]
        window = self.Window("mylauncher", buttons)
        other = self.Window("other", [self.Button() for _ in range(3)])
        logged = []
        self.assertTrue(apply_style("mylauncher", "#1c1c1f", self.appkit([other, window]), logged.append))
        self.assertTrue(all(b.hidden for b in buttons))
        self.assertFalse(any(b.hidden for b in other.buttons))  # only OUR window
        names = dict(window.calls)
        self.assertEqual(names["setTitleVisibility_"], 1)
        self.assertTrue(names["setTitlebarAppearsTransparent_"])
        self.assertTrue(names["setMovableByWindowBackground_"])
        self.assertEqual(names["setBackgroundColor_"][0], "color")
        self.assertEqual(logged, [])

    def test_no_such_window_or_a_failure_keeps_the_normal_window(self):
        from mychrome import apply_style

        logged = []
        self.assertFalse(apply_style("mylauncher", "#000000", self.appkit([]), logged.append))
        self.assertIn("no window called", logged[0])

        class Broken(self.Window):
            def setTitleVisibility_(self, value):
                raise RuntimeError("objc error")

        logged.clear()
        self.assertFalse(apply_style("mylauncher", "#000000", self.appkit([Broken("mylauncher", [None] * 3)]), logged.append))
        self.assertIn("objc error", logged[0])

    def test_missing_pyobjc_is_explained(self):
        import sys
        from unittest import mock
        from mychrome import apply_style

        logged = []
        with mock.patch.dict(sys.modules, {"AppKit": None}):
            self.assertFalse(apply_style("x", "#000000", None, logged.append))
        self.assertIn("pyobjc", logged[0])

    def test_hex_to_rgb(self):
        from mychrome import hex_to_rgb

        self.assertEqual(hex_to_rgb("#ff0000"), (1.0, 0.0, 0.0))
