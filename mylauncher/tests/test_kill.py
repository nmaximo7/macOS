"""mykill.py and the kill_app action, against a pretend Mac (support.FakeSystem)."""

import unittest

import support
from myactions import RunOptions, run_item
from mykill import alive, applescript_quote, running_apps
from mytypes import Item

OBSIDIAN, GHOSTTY = "/Applications/Obsidian.app", "/Applications/Ghostty.app"
CODE = "/Applications/Visual Studio Code.app"


def system(**kw):
    s = support.FakeSystem({OBSIDIAN: [812], GHOSTTY: [20, 21], CODE: [77], "/Applications/Python.app": [5]}, **kw)
    s.add_noise()
    return s


class Listing(unittest.TestCase):
    def test_lists_apps_not_helpers_or_system_ui(self):
        apps = running_apps(system(), protected=("python",))
        self.assertEqual([a.name for a in apps], ["Ghostty", "Obsidian", "Visual Studio Code"])

    def test_pids_are_grouped_and_paths_may_contain_spaces(self):
        apps = {a.name: a for a in running_apps(system())}
        self.assertEqual(apps["Ghostty"].pids, (20, 21))
        self.assertEqual(apps["Visual Studio Code"].path, CODE)

    def test_protected_names_ignore_case(self):
        self.assertNotIn("Python", [a.name for a in running_apps(system(), protected=("python",))])
        self.assertIn("Python", [a.name for a in running_apps(system(), protected=())])

    def test_ps_missing_means_nothing_running(self):
        def broken(command):
            raise FileNotFoundError()

        self.assertEqual(running_apps(broken), [])
        self.assertEqual(alive(broken, [1]), [])

    def test_alive(self):
        s = system()
        self.assertEqual(alive(s, [812, 999]), [812])
        self.assertEqual(alive(s, []), [])

    def test_applescript_quote(self):
        self.assertEqual(applescript_quote('/A "b"\\c'), '/A \\"b\\"\\\\c')


def kill(path, s, **opts):
    name = path.rsplit("/", 1)[-1].removesuffix(".app")
    item = Item(f"kill:{name}", f"Kill {name}", "kill", "kill_app", target=path)
    options = RunOptions(sleep=opts.pop("sleep", lambda seconds: None), **opts)
    return run_item(item, runner=s, options=options)


class Killing(unittest.TestCase):
    def test_polite_quit_works(self):
        s = system()
        result = kill(OBSIDIAN, s)
        self.assertTrue(result.ok)
        self.assertFalse(result.needs_force)
        self.assertNotIn(812, s.procs)
        osascript = next(c for c in s.calls if c[0] == "osascript")
        self.assertIn(f'tell application "{OBSIDIAN}" to quit', osascript[-1])
        self.assertFalse(any(c[0] == "kill" for c in s.calls))  # never force when it was not needed

    def test_waits_for_a_slow_app(self):
        s = system(quits=False)
        ticks = []

        def sleep(seconds):  # the app quits by itself after the third look
            ticks.append(seconds)
            if len(ticks) == 3:
                s.procs.pop(812)

        result = kill(OBSIDIAN, s, sleep=sleep)
        self.assertTrue(result.ok)
        self.assertEqual(len(ticks), 3)
        self.assertFalse(any(c[0] == "kill" for c in s.calls))

    def test_frozen_app_asks_instead_of_forcing(self):
        s = system(quits=False, term_works=False)
        result = kill(OBSIDIAN, s, grace=2)
        self.assertFalse(result.ok)
        self.assertTrue(result.needs_force)
        self.assertIn("--force", result.message)
        self.assertIn(812, s.procs)  # still there: nothing was forced
        self.assertFalse(any(c[:2] == ["kill", "-KILL"] for c in s.calls))

    def test_grace_period_is_respected(self):
        s = system(quits=False, term_works=False)
        waits = []
        kill(OBSIDIAN, s, grace=1, sleep=waits.append)
        self.assertEqual(len(waits), 4)  # 1 second / 0.25 s

    def test_force_goes_straight_to_kill_minus_kill(self):
        s = system(quits=False, term_works=False)
        result = kill(OBSIDIAN, s, force=True)
        self.assertTrue(result.ok)
        self.assertNotIn(812, s.procs)
        self.assertFalse(any(c[0] == "osascript" for c in s.calls))  # no polite request this time
        self.assertIn(["kill", "-KILL", "812"], s.calls)

    def test_auto_force(self):
        s = system(quits=False, term_works=False)
        result = kill(GHOSTTY, s, grace=1, auto_force=True)
        self.assertTrue(result.ok)
        self.assertEqual(s.procs.keys() & {20, 21}, set())
        self.assertIn(["kill", "-KILL", "20", "21"], s.calls)

    def test_refused_apple_event_falls_back_to_term(self):
        s = system(osascript_fails=True)
        result = kill(OBSIDIAN, s)
        self.assertTrue(result.ok)
        self.assertIn(["kill", "-TERM", "812"], s.calls)

    def test_a_process_that_survives_even_kill_is_reported(self):
        s = system(quits=False, term_works=False)
        original = s.__call__

        def stubborn(command):
            if command[:2] == ["kill", "-KILL"]:
                return original(["true"])  # pretend KILL did nothing
            return original(command)

        result = kill(OBSIDIAN, stubborn, force=True)
        self.assertFalse(result.ok)
        self.assertIn("could not force quit", result.message)

    def test_not_running(self):
        s = system()
        s.procs.pop(812)
        result = kill(OBSIDIAN, s)
        self.assertFalse(result.ok)
        self.assertIn("not running", result.message)
        self.assertFalse(any(c[0] == "osascript" for c in s.calls))

    def test_dry_run_touches_nothing(self):
        s = system()
        item = Item("kill:Obsidian", "Kill Obsidian", "kill", "kill_app", target=OBSIDIAN)
        result = run_item(item, runner=s, dry_run=True)
        self.assertTrue(result.ok)
        self.assertEqual(s.calls, [])
        self.assertIn("Would run", result.message)


if __name__ == "__main__":
    unittest.main()
