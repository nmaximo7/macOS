"""myactions.py: doing things (with a fake runner: nothing real is ever run)."""

import unittest

import support
from myactions import ACTIONS, COMMAND_ACTIONS, run_item
from mytypes import Item


class Opening(support.TempDirCase):
    def item(self, path):
        return Item("app:X", "Run X", "app", "open_app", target=str(path))

    def test_open_runs_the_open_command(self):
        folder = self.make_apps("A", "X")
        runner = support.FakeRunner()
        result = run_item(self.item(folder / "X.app"), runner=runner)
        self.assertTrue(result.ok)
        self.assertEqual(runner.calls, [["open", str(folder / "X.app")]])

    def test_dry_run_runs_nothing(self):
        runner = support.FakeRunner()
        result = run_item(self.item("/Applications/X.app"), runner=runner, dry_run=True)
        self.assertTrue(result.ok)
        self.assertEqual(runner.calls, [])
        self.assertIn("Would run: open /Applications/X.app", result.message)

    def test_app_that_disappeared(self):
        runner = support.FakeRunner()
        result = run_item(self.item(self.tmp / "gone.app"), runner=runner)
        self.assertFalse(result.ok)
        self.assertIn("does not exist", result.message)
        self.assertEqual(runner.calls, [])

    def test_command_failure_shows_the_error(self):
        folder = self.make_apps("A", "X")
        result = run_item(self.item(folder / "X.app"), runner=support.FakeRunner(returncode=1, stderr="boom"))
        self.assertFalse(result.ok)
        self.assertIn("boom", result.message)

    def test_missing_program(self):
        folder = self.make_apps("A", "X")
        result = run_item(self.item(folder / "X.app"), runner=support.FakeRunner(error=FileNotFoundError()))
        self.assertFalse(result.ok)
        self.assertIn("'open' was not found", result.message)

    def test_paths_with_spaces_stay_one_argument(self):
        folder = self.make_apps("My Apps", "Visual Studio Code")
        runner = support.FakeRunner()
        run_item(self.item(folder / "Visual Studio Code.app"), runner=runner)
        self.assertEqual(len(runner.calls[0]), 2)


class Shutdown(unittest.TestCase):
    ITEM = Item("cmd:shutdown", "Shutdown", "command", "shutdown", confirm=True)

    def test_uses_system_events(self):
        runner = support.FakeRunner()
        self.assertTrue(run_item(self.ITEM, runner=runner).ok)
        self.assertEqual(runner.calls[0][0], "osascript")
        self.assertIn("shut down", runner.calls[0][-1])

    def test_dry_run_does_not_shut_down(self):
        runner = support.FakeRunner()
        run_item(self.ITEM, runner=runner, dry_run=True)
        self.assertEqual(runner.calls, [])


class Registry(unittest.TestCase):
    def test_unknown_action(self):
        result = run_item(Item("x", "X", "command", "explode"), runner=support.FakeRunner())
        self.assertFalse(result.ok)
        self.assertIn("unknown action", result.message)

    def test_every_command_action_exists_and_open_app_is_registered(self):
        # If you add a function to ACTIONS but forget COMMAND_ACTIONS (or the reverse), this test tells you.
        self.assertIn("open_app", ACTIONS)
        for name in COMMAND_ACTIONS:
            self.assertIn(name, ACTIONS)


if __name__ == "__main__":
    unittest.main()
