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
        {"id": "cmd:shutdown", "title": "Shutdown", "kind": "command", "confirm": True, "complete": "", "icon": "🔌", "badge": "Command", "subtitle": "Turn the Mac off"},
        {"id": "app:Obsidian", "title": "Run Obsidian", "kind": "app", "confirm": False, "complete": "", "icon": "🚀", "badge": "Application", "subtitle": "/Applications"},
        {"id": "app:Safari", "title": "Run Safari", "kind": "app", "confirm": False, "complete": "", "icon": "🚀", "badge": "Application", "subtitle": "/Applications"},
        {"id": "prefix:kill", "title": "Close an app (kill <name>)", "kind": "prefix", "confirm": False, "complete": "kill ", "icon": "💀", "badge": "Hint", "subtitle": ""},
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
        first = text.split()[0].lower() if text.split() else ""
        mode, highlight = {"kill": ("kill", 4), "run": ("run", 3), ";": ("snippets", 1)}.get(first, ("normal", 0))
        return {"query": text, "completion": results[0]["title"].lower() if results else text, "results": results, "mode": mode, "highlight": highlight}

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

        self.styled = []
        self.config = config
        self.window = LauncherWindow(
            self.root, self.engine, config, front=lambda: self.fronted.append(1), confirm=confirm,
            style=lambda title, background: self.styled.append((title, background)) or True,
        )

    def listed(self):
        """The titles of the visible rows."""
        return [row[1] for row in self.window.list.texts()]

    def test_show_lists_everything_and_takes_the_focus(self):
        self.window.show()
        self.assertTrue(self.window.visible)
        self.assertEqual(self.listed(), ["Shutdown", "Run Obsidian", "Run Safari", "Close an app (kill <name>)"])
        self.assertEqual(self.fronted, [1])

    def test_typing_filters(self):
        self.window.show()
        self.window.input.set("obs")
        self.assertEqual(self.listed(), ["Run Obsidian"])

    def test_down_and_up_move_the_selection(self):
        self.window.show()
        self.window._move(+1)
        self.assertEqual(self.window.state.selected, 1)
        self.window._move(-1)
        self.window._move(-1)
        self.assertEqual(self.window.state.selected, 3)  # wrapped to the last of the four items

    def test_tab_autocompletes(self):
        self.window.show()
        self.window.input.set("obs")
        self.assertEqual(self.window._autocomplete(), "break")
        self.assertEqual(self.window.input.get(), "run obsidian")

    def test_enter_runs_the_selected_item_and_hides(self):
        self.window.show()
        self.window.input.set("saf")
        self.window._run_selected()
        self.assertEqual(self.engine.ran, ["app:Safari"])
        self.assertFalse(self.window.visible)
        self.assertEqual(self.asked, [])  # apps do not ask

    def test_shutdown_asks_and_no_does_nothing(self):
        self.window.show()
        self.window.input.set("shut")
        self.answers = [False]
        self.window._run_selected()
        self.assertEqual(self.asked, ["Shutdown: are you sure?"])
        self.assertEqual(self.engine.ran, [])
        self.assertTrue(self.window.visible)

    def test_shutdown_yes_runs(self):
        self.window.show()
        self.window.input.set("shut")
        self.answers = [True]
        self.window._run_selected()
        self.assertEqual(self.engine.ran, ["cmd:shutdown"])

    def test_failure_is_shown_and_window_stays(self):
        self.engine.run_results = [RunResult(False, "boom")]
        self.window.show()
        self.window.input.set("saf")
        self.window._run_selected()
        self.assertTrue(self.window.visible)
        self.assertIn("boom", self.window.status.cget("text"))

    def test_snippet_text_is_shown_after_the_trigger(self):
        self.engine.ITEMS = [*FakeEngine.ITEMS, {"id": "snip:;bsite", "title": ";bsite", "kind": "snippet", "confirm": False, "complete": ";bsite", "subtitle": "https://justtothepoint.com/", "icon": "✂️", "badge": "Snippet"}]
        self.window.show()
        self.window.input.set(";bs")
        self.assertEqual(self.engine.search(";bs")["results"][0]["title"], ";bsite")
        self.window.input.set("")
        self.window.input.set(";bsite")
        self.assertEqual(self.window.list.texts(), [("✂️", ";bsite", "https://justtothepoint.com/", "Snippet")])

    def test_enter_on_a_hint_completes_instead_of_running(self):
        self.window.show()
        self.window.input.set("kill")  # only the hint matches
        self.assertEqual(self.listed(), ["Close an app (kill <name>)"])
        self.window._run_selected()
        self.assertEqual(self.window.input.get(), "kill ")
        self.assertEqual(self.engine.calls, [])
        self.assertTrue(self.window.visible)

    def test_the_typed_text_is_passed_to_the_engine(self):
        self.window.show()
        self.window.input.set("saf")
        self.window._run_selected()
        self.assertEqual(self.engine.calls, [("app:Safari", "saf", False)])

    def test_frozen_app_asks_to_force_quit_and_yes_forces(self):
        self.engine.run_results = [RunResult(False, "Obsidian did not quit", needs_force=True), RunResult(True, "force quit")]
        self.window.show()
        self.window.input.set("obs")
        self.answers = [True]
        self.window._run_selected()
        self.assertIn("Force quit now?", self.asked[0])
        self.assertEqual(self.engine.calls, [("app:Obsidian", "obs", False), ("app:Obsidian", "obs", True)])
        self.assertFalse(self.window.visible)

    def test_frozen_app_and_no_leaves_it_alone(self):
        self.engine.run_results = [RunResult(False, "Obsidian did not quit", needs_force=True)]
        self.window.show()
        self.window.input.set("obs")
        self.answers = [False]
        self.window._run_selected()
        self.assertEqual(self.engine.calls, [("app:Obsidian", "obs", False)])
        self.assertTrue(self.window.visible)
        self.assertIn("did not quit", self.window.status.cget("text"))

    def test_enter_with_no_suggestions_does_nothing(self):
        self.window.show()
        self.window.input.set("qqq")
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
        self.window.input.set("obs")
        self.window.hide()
        self.window.show()
        self.assertEqual(self.window.input.get(), "")


@unittest.skipIf(tk is None, "tkinter is not installed")
class Look(Window):
    """The Raycast-like part: colours, rows with emoji, mode label, scrolling, no title-bar buttons."""

    def test_rows_have_emoji_title_info_and_label(self):
        self.window.show()
        self.assertEqual(self.window.list.texts()[0], ("🔌", "Shutdown", "Turn the Mac off", "Command"))
        self.assertEqual(self.window.list.texts()[3], ("💀", "Close an app (kill <name>)", "", "Hint"))

    def test_the_recognised_command_is_painted(self):
        self.window.show()
        self.window.input.set("kill saf")
        ranges = self.window.input.text.tag_ranges("command")
        self.assertEqual([str(r) for r in ranges], ["1.0", "1.4"])  # "kill" only
        self.assertEqual(self.window.mode.cget("text"), "💀 Close an app")
        self.window.input.set("saf")
        self.assertEqual(self.window.input.text.tag_ranges("command"), ())  # nothing recognised: no colour
        self.assertEqual(self.window.mode.cget("text"), "")

    def test_highlight_never_goes_past_the_text(self):
        self.window.show()
        self.window.input.set("run")  # the engine says 3 characters: that is all of it
        self.assertEqual([str(r) for r in self.window.input.text.tag_ranges("command")], ["1.0", "1.3"])

    def test_the_colour_comes_from_the_configuration(self):
        self.assertEqual(str(self.window.input.text.tag_cget("command", "foreground")), "#ff9f0a")
        self.assertEqual(self.window.root.cget("bg"), "#1c1c1f")

    def test_the_window_is_styled_once_without_title_bar_buttons(self):
        self.window.show()
        self.window.hide()
        self.window.show()
        self.assertEqual(self.styled, [(self.config.window_title, "#1c1c1f")])

    def test_standard_style_leaves_the_normal_window(self):
        config = parse_config(support.good_config(window={"style": "standard"}), Path("x"))
        window = LauncherWindow(self.root, self.engine, config, front=lambda: None, style=lambda *a: self.styled.append(a))
        window.show()
        self.assertEqual(self.styled, [])

    def test_a_failed_styling_is_tried_again_next_time(self):
        calls = []
        window = LauncherWindow(self.root, self.engine, self.config, front=lambda: None, style=lambda *a: calls.append(a) and False)
        window.show()
        window.hide()
        window.show()
        self.assertEqual(len(calls), 2)

    def test_the_window_is_as_tall_as_its_rows(self):
        self.window.show()
        tall = self.root.winfo_reqheight()
        self.window.input.set("shut")  # one result
        self.assertLess(self.root.winfo_reqheight(), tall)

    def test_a_long_list_scrolls_and_clicking_runs(self):
        many = [{"id": f"app:A{i}", "title": f"Run A{i}", "kind": "app", "confirm": False, "complete": "", "icon": "🚀", "badge": "Application", "subtitle": ""} for i in range(20)]
        self.engine.ITEMS = many
        self.window.show()
        self.assertEqual(len(self.window.list.texts()), 8)  # search.max_results rows on screen
        for _ in range(9):
            self.window._move(+1)
        self.assertEqual(self.window.state.selected, 9)
        self.assertEqual(self.listed()[-1], "Run A9")  # scrolled so the selected row is the last visible one
        self.window._clicked(0)  # the first visible row is now A2
        self.assertEqual(self.engine.ran, ["app:A2"])

    def test_a_long_subtitle_is_cut(self):
        self.engine.ITEMS = [{"id": "snip:;x", "title": ";x", "kind": "snippet", "confirm": False, "complete": ";x", "subtitle": "word " * 200, "icon": "✂️", "badge": "Snippet"}]
        self.window.show()
        self.assertLess(len(self.window.list.texts()[0][2]), 100)
        self.assertTrue(self.window.list.texts()[0][2].endswith("…"))

    def test_enter_on_a_snippet_group_writes_the_group(self):
        self.engine.ITEMS = [{"id": "group:;p", "title": ";p  prompts", "kind": "prefix", "confirm": False, "complete": ";p", "icon": "🧠", "badge": "Group", "subtitle": "3 snippet(s)"}]
        self.window.show()
        self.window._run_selected()
        self.assertEqual(self.window.input.get(), ";p")


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
