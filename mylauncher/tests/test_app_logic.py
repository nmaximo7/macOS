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
