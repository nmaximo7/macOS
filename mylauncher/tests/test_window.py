"""app/mywindow.py with a REAL tkinter window. Skipped when tkinter or a screen is not available."""

import unittest

import support

try:
    import tkinter as tk

    from mywindow import LauncherWindow, bring_to_front
except ImportError:  # tkinter not installed: macOS Homebrew needs  brew install python-tk
    tk = None

from myconfig import parse_config
from myengine import RunResult
from pathlib import Path


class FakeEngine:
    """Answers searches from a small list, and remembers what it was asked to run."""

    ITEMS = [
        {"id": "cmd:shutdown", "title": "Shutdown", "kind": "command", "confirm": True, "complete": ""},
        {"id": "app:Obsidian", "title": "Run Obsidian", "kind": "app", "confirm": False, "complete": ""},
        {"id": "app:Safari", "title": "Run Safari", "kind": "app", "confirm": False, "complete": ""},
        {"id": "prefix:kill", "title": "Close an app (kill <name>)", "kind": "prefix", "confirm": False, "complete": "kill "},
    ]

    def __init__(self, run_results=None):
        self.calls, self.searches = [], []
        self.run_results = list(run_results or [RunResult(True, "ok")])  # answers, in order; the last one repeats

    @property
    def ran(self):
        return [c[0] for c in self.calls]

    def search(self, text):
        self.searches.append(text)
        results = [i for i in self.ITEMS if text.lower() in i["title"].lower()]  # ITEMS may be replaced per test
        return {"query": text, "completion": results[0]["title"].lower() if results else text, "results": results}

    def run(self, item_id, text="", force=False):
        self.calls.append((item_id, text, force))
        return self.run_results.pop(0) if len(self.run_results) > 1 else self.run_results[0]


@unittest.skipIf(tk is None, "tkinter is not installed")
class Window(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("no screen available")
        self.addCleanup(self.root.destroy)
        self.engine = FakeEngine()
        self.answers = []  # what the user "clicks" in the confirmation question
        self.asked = []
        self.fronted = []
        config = parse_config(support.good_config(), Path("x"))

        def confirm(title, message, parent=None):
            self.asked.append(message)
            return self.answers.pop(0)

        self.window = LauncherWindow(self.root, self.engine, config, front=lambda: self.fronted.append(1), confirm=confirm)

    def listed(self):
        return list(self.window.listbox.get(0, "end"))

    def test_show_lists_everything_and_takes_the_focus(self):
        self.window.show()
        self.assertTrue(self.window.visible)
        self.assertEqual(self.listed(), ["Shutdown", "Run Obsidian", "Run Safari", "Close an app (kill <name>)"])
        self.assertEqual(self.fronted, [1])

    def test_typing_filters(self):
        self.window.show()
        self.window.text.set("obs")
        self.assertEqual(self.listed(), ["Run Obsidian"])

    def test_down_and_up_move_the_selection(self):
        self.window.show()
        self.window._move(+1)
        self.assertEqual(self.window.listbox.curselection(), (1,))
        self.window._move(-1)
        self.window._move(-1)
        self.assertEqual(self.window.listbox.curselection(), (3,))  # wrapped to the last of the four items

    def test_tab_autocompletes(self):
        self.window.show()
        self.window.text.set("obs")
        self.assertEqual(self.window._autocomplete(), "break")
        self.assertEqual(self.window.text.get(), "run obsidian")

    def test_enter_runs_the_selected_item_and_hides(self):
        self.window.show()
        self.window.text.set("saf")
        self.window._run_selected()
        self.assertEqual(self.engine.ran, ["app:Safari"])
        self.assertFalse(self.window.visible)
        self.assertEqual(self.asked, [])  # apps do not ask

    def test_shutdown_asks_and_no_does_nothing(self):
        self.window.show()
        self.window.text.set("shut")
        self.answers = [False]
        self.window._run_selected()
        self.assertEqual(self.asked, ["Shutdown: are you sure?"])
        self.assertEqual(self.engine.ran, [])
        self.assertTrue(self.window.visible)

    def test_shutdown_yes_runs(self):
        self.window.show()
        self.window.text.set("shut")
        self.answers = [True]
        self.window._run_selected()
        self.assertEqual(self.engine.ran, ["cmd:shutdown"])

    def test_failure_is_shown_and_window_stays(self):
        self.engine.run_results = [RunResult(False, "boom")]
        self.window.show()
        self.window.text.set("saf")
        self.window._run_selected()
        self.assertTrue(self.window.visible)
        self.assertIn("boom", self.window.status.cget("text"))

    def test_snippet_text_is_shown_after_the_trigger(self):
        self.engine.ITEMS = [*FakeEngine.ITEMS, {"id": "snip:;bsite", "title": ";bsite", "kind": "snippet", "confirm": False, "complete": ";bsite", "subtitle": "https://justtothepoint.com/"}]
        self.window.show()
        self.window.text.set(";bs")
        self.assertEqual(self.engine.search(";bs")["results"][0]["title"], ";bsite")
        self.window.text.set("")
        self.window.text.set(";bsite")
        self.assertEqual(self.listed(), [";bsite   https://justtothepoint.com/"])

    def test_enter_on_a_hint_completes_instead_of_running(self):
        self.window.show()
        self.window.text.set("kill")  # only the hint matches
        self.assertEqual(self.listed(), ["Close an app (kill <name>)"])
        self.window._run_selected()
        self.assertEqual(self.window.text.get(), "kill ")
        self.assertEqual(self.engine.calls, [])
        self.assertTrue(self.window.visible)

    def test_the_typed_text_is_passed_to_the_engine(self):
        self.window.show()
        self.window.text.set("saf")
        self.window._run_selected()
        self.assertEqual(self.engine.calls, [("app:Safari", "saf", False)])

    def test_frozen_app_asks_to_force_quit_and_yes_forces(self):
        self.engine.run_results = [RunResult(False, "Obsidian did not quit", needs_force=True), RunResult(True, "force quit")]
        self.window.show()
        self.window.text.set("obs")
        self.answers = [True]
        self.window._run_selected()
        self.assertIn("Force quit now?", self.asked[0])
        self.assertEqual(self.engine.calls, [("app:Obsidian", "obs", False), ("app:Obsidian", "obs", True)])
        self.assertFalse(self.window.visible)

    def test_frozen_app_and_no_leaves_it_alone(self):
        self.engine.run_results = [RunResult(False, "Obsidian did not quit", needs_force=True)]
        self.window.show()
        self.window.text.set("obs")
        self.answers = [False]
        self.window._run_selected()
        self.assertEqual(self.engine.calls, [("app:Obsidian", "obs", False)])
        self.assertTrue(self.window.visible)
        self.assertIn("did not quit", self.window.status.cget("text"))

    def test_enter_with_no_suggestions_does_nothing(self):
        self.window.show()
        self.window.text.set("qqq")
        self.window._run_selected()
        self.assertEqual(self.engine.ran, [])

    def test_engine_problem_is_shown_not_raised(self):
        def broken(text):
            raise RuntimeError("engine down")

        self.engine.search = broken
        self.window.refresh()
        self.assertIn("engine down", self.window.status.cget("text"))

    def test_escape_and_toggle(self):
        self.window.show()
        self.window.hide()
        self.assertFalse(self.window.visible)
        self.window.toggle()
        self.assertTrue(self.window.visible)
        self.window.toggle()
        self.assertFalse(self.window.visible)

    def test_show_resets_the_text(self):
        self.window.show()
        self.window.text.set("obs")
        self.window.hide()
        self.window.show()
        self.assertEqual(self.window.text.get(), "")


@unittest.skipIf(tk is None, "tkinter is not installed")
class FrontTrick(unittest.TestCase):
    def test_asks_system_events_for_our_pid(self):
        calls = []
        bring_to_front(runner=lambda command, **kw: calls.append(command), pid=4242)
        self.assertEqual(calls[0][0], "osascript")
        self.assertIn("unix id is 4242", calls[0][-1])

    def test_missing_osascript_is_not_an_error(self):
        def missing(command, **kw):
            raise FileNotFoundError()

        bring_to_front(runner=missing)  # must not raise


if __name__ == "__main__":
    unittest.main()
