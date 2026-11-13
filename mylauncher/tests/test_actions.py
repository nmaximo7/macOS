"""myactions.py: doing things (with a fake runner: nothing real is ever run)."""

import unittest

import support
from myactions import ACTIONS, COMMAND_ACTIONS, RunOptions, run_item
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


class DefaultRunner(unittest.TestCase):
    """default_runner really starts a program: here the harmless `cat`, which prints what it receives."""

    def test_input_is_sent_as_utf_8_and_lang_is_set_for_the_command(self):
        import shutil

        from myactions import default_runner

        if not shutil.which("env") or not shutil.which("cat"):
            self.skipTest("needs env and cat")
        done = default_runner(["cat"], input_text="línea ñ 😀\n")
        self.assertEqual((done.returncode, done.stdout), (0, "línea ñ 😀\n"))
        # LANG is forced to UTF-8 when we send text (pbcopy needs it when macOS starts us at login)
        done = default_runner(["env"], input_text="")
        self.assertIn("LANG=en_US.UTF-8", done.stdout)

    def test_without_input_the_environment_is_left_alone(self):
        import os
        import shutil

        from myactions import default_runner

        if not shutil.which("env"):
            self.skipTest("needs env")
        done = default_runner(["env"])
        self.assertEqual("LANG=en_US.UTF-8" in done.stdout, os.environ.get("LANG") == "en_US.UTF-8")


class OpenUrl(unittest.TestCase):
    def item(self, url):
        return Item("link:x", "Search x", "quicklink", "open_url", target=url)

    def test_opens_web_addresses(self):
        runner = support.FakeRunner()
        self.assertTrue(run_item(self.item("https://a.test/?q=1"), runner=runner).ok)
        self.assertEqual(runner.calls, [["open", "https://a.test/?q=1"]])

    def test_refuses_anything_that_is_not_http(self):
        for url in ("file:///etc/passwd", "javascript:alert(1)", "/Applications/Safari.app", "ftp://x.test", ""):
            runner = support.FakeRunner()
            with self.subTest(url=url):
                result = run_item(self.item(url), runner=runner)
                self.assertFalse(result.ok)
                self.assertEqual(runner.calls, [])


class OpenUrlInTab(unittest.TestCase):
    URL = "https://a.test/?q=1"
    ITEM = Item("link:x", "Search x", "quicklink", "open_url", target=URL)
    BROWSER = ("/Applications/Zen.app/Contents/MacOS/zen", "-new-tab", "{url}")

    def run_it(self, runner, dry_run=False):
        return run_item(self.ITEM, runner=runner, dry_run=dry_run, options=RunOptions(browser_command=self.BROWSER))

    def test_uses_the_browser_command_with_the_url_filled_in(self):
        runner = support.FakeRunner()
        result = self.run_it(runner)
        self.assertTrue(result.ok)
        self.assertEqual(runner.calls, [["/Applications/Zen.app/Contents/MacOS/zen", "-new-tab", self.URL]])
        self.assertIn("new tab", result.message)

    def test_falls_back_to_open_when_the_program_is_missing(self):
        calls = []

        def runner(command, input_text=None):
            calls.append(command)
            if command[0] != "open":
                raise FileNotFoundError
            return support.FakeRunner()(command)

        result = self.run_it(runner)
        self.assertTrue(result.ok)
        self.assertEqual(calls[-1], ["open", self.URL])

    def test_falls_back_to_open_when_the_command_fails(self):
        results = iter([1, 0])

        def runner(command, input_text=None):
            return support.FakeRunner(returncode=next(results))(command)

        self.assertTrue(self.run_it(runner).ok)

    def test_dry_run_shows_the_browser_command_and_runs_nothing(self):
        runner = support.FakeRunner()
        result = self.run_it(runner, dry_run=True)
        self.assertEqual(runner.calls, [])
        self.assertIn("-new-tab", result.message)

    def test_still_refuses_non_http(self):
        runner = support.FakeRunner()
        item = Item("x", "x", "quicklink", "open_url", target="file:///etc/passwd")
        self.assertFalse(run_item(item, runner=runner, options=RunOptions(browser_command=self.BROWSER)).ok)
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
        for name in ("open_url", "kill_app", "prefix_hint"):
            self.assertIn(name, ACTIONS)


if __name__ == "__main__":
    unittest.main()
