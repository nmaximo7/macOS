"""app/: everything of the window that does NOT need a screen (state, engine client, hotkey)."""

import json
import subprocess
import unittest
from types import SimpleNamespace

import support  # noqa: F401  (puts cli/ and app/ on the import path)
from myengine import Engine, EngineError
from myhotkey import HotkeyListener, describe, to_pynput
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
        self.assertEqual(self.engine(process).run("app:Safari"), (True, "done"))
        self.assertEqual(process.calls[0], ["PY", "SCRIPT", "run", "--json", "--id", "app:Safari", "--yes"])

    def test_run_failure_messages(self):
        self.assertEqual(self.engine(FakeProcess(json.dumps({"error": "no item"}))).run("x"), (False, "no item"))


class Hotkey(unittest.TestCase):
    def test_translation(self):
        self.assertEqual(to_pynput(("command",), "d"), "<cmd>+d")
        self.assertEqual(to_pynput(("command", "shift", "option", "control"), "d"), "<cmd>+<shift>+<alt>+<ctrl>+d")
        self.assertEqual(describe(("command",), "d"), "command+d")

    def test_listener_registers_the_combination_and_stops(self):
        made = {}

        class FakeHotKeys:
            def __init__(self, mapping):
                made["mapping"], self.started, self.stopped = mapping, False, False
                made["obj"] = self

            def start(self):
                self.started = True

            def stop(self):
                self.stopped = True

        pressed = []
        listener = HotkeyListener(("command",), "d", lambda: pressed.append(1), factory=FakeHotKeys)
        listener.start()
        self.assertTrue(made["obj"].started)
        made["mapping"]["<cmd>+d"]()  # "press" the keys
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


if __name__ == "__main__":
    unittest.main()
