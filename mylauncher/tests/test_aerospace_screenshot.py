"""Step 10: AeroSpace workspaces when an app opens, `reboot`, and the two `screenshot` commands (+ help screenshot)."""

import json
import os
import plistlib
import stat
import subprocess
import unittest
from pathlib import Path

import support
import myaerospace
import myhelp
from myactions import RunOptions, run_item, screenshot_script
from myconfig import ConfigError, parse_config
from mytypes import Item
from test_cli import CliCase

TOML = """\
[[on-window-detected]]
if.app-id = 'com.microsoft.VSCode'
run = 'move-node-to-workspace C'

[[on-window-detected]]
if.app-id = 'app.zen-browser.zen'
run = ['layout floating', 'move-node-to-workspace --focus-follows-window B']

[[on-window-detected]]
if.app-name-regex-substring = 'obsidian'
run = 'move-node-to-workspace O'

[[on-window-detected]]
if.app-id = 'com.apple.finder'
run = 'layout floating'
"""


class Rules(support.TempDirCase):
    def toml(self, text=TOML):
        path = self.tmp / "aerospace.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_rules_are_read_from_the_toml(self):
        rules, problem = myaerospace.read_rules(self.toml())
        self.assertEqual(problem, "")
        self.assertEqual(
            rules,
            [myaerospace.Rule("C", "com.microsoft.VSCode"), myaerospace.Rule("B", "app.zen-browser.zen"), myaerospace.Rule("O", "", "obsidian")],
        )  # the finder rule moves nothing: not a workspace rule

    def test_missing_or_broken_file_is_a_problem_not_a_crash(self):
        self.assertIn("does not exist", myaerospace.read_rules(self.tmp / "nope.toml")[1])
        self.assertIn("cannot read", myaerospace.read_rules(self.toml("[[oops"))[1])

    def test_explicit_choice_beats_the_toml_and_names_are_case_insensitive(self):
        rules, _ = myaerospace.read_rules(self.toml())
        ws = myaerospace.workspace_for("/x/Code.app", "Visual Studio Code", {"visual studio code": "Z"}, rules, read_id=lambda p: "com.microsoft.VSCode")
        self.assertEqual(ws, "Z")

    def test_app_id_then_name_regex_then_nothing(self):
        rules, _ = myaerospace.read_rules(self.toml())
        ids = {"/x/Code.app": "com.microsoft.VSCode", "/x/Obsidian.app": "md.obsidian", "/x/Safari.app": "com.apple.Safari"}
        read = lambda p: ids[p]
        self.assertEqual(myaerospace.workspace_for("/x/Code.app", "Visual Studio Code", {}, rules, read), "C")
        self.assertEqual(myaerospace.workspace_for("/x/Obsidian.app", "Obsidian", {}, rules, read), "O")
        self.assertEqual(myaerospace.workspace_for("/x/Safari.app", "Safari", {}, rules, read), "")

    def test_bundle_id_is_read_from_info_plist(self):
        app = self.tmp / "Code.app"
        (app / "Contents").mkdir(parents=True)
        (app / "Contents" / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "com.microsoft.VSCode"}))
        self.assertEqual(myaerospace.bundle_id(app), "com.microsoft.VSCode")
        self.assertEqual(myaerospace.bundle_id(self.tmp / "none.app"), "")

    def test_find_command_uses_path_then_the_usual_places(self):
        self.assertEqual(myaerospace.find_command("aerospace", which=lambda c: "/p/aerospace"), "/p/aerospace")
        self.assertEqual(myaerospace.find_command("aerospace", which=lambda c: None, exists=lambda p: p == "/opt/homebrew/bin/aerospace"), "/opt/homebrew/bin/aerospace")
        self.assertEqual(myaerospace.find_command("aerospace", which=lambda c: None, exists=lambda p: False), "")


class OpeningAnApp(support.TempDirCase):
    def setUp(self):
        super().setUp()
        self.app = self.tmp / "Visual Studio Code.app"
        (self.app / "Contents").mkdir(parents=True)
        (self.app / "Contents" / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "com.microsoft.VSCode"}))
        self.toml = self.tmp / "aerospace.toml"
        self.toml.write_text(TOML, encoding="utf-8")
        self.program = self.tmp / "aerospace"
        self.program.write_text("#!/bin/sh\n")
        self.program.chmod(0o755)
        self.item = Item(id="app:code", title="Visual Studio Code", kind="app", action="open_app", target=str(self.app))

    def options(self, **changes):
        base = dict(aerospace=True, aerospace_command=str(self.program), aerospace_config=self.toml)
        return RunOptions(**{**base, **changes})

    def test_it_goes_to_the_workspace_FIRST_and_then_opens_the_app(self):
        runner = support.FakeRunner()
        result = run_item(self.item, runner, options=self.options())
        self.assertTrue(result.ok)
        self.assertEqual([tuple(c) for c in runner.calls], [(str(self.program), "workspace", "C"), ("open", str(self.app))])
        self.assertEqual(result.message, "opened Visual Studio Code (AeroSpace workspace C)")

    def test_run_prefix_in_the_title_is_not_part_of_the_name(self):
        runner = support.FakeRunner()
        item = Item(id="app:code", title="Run Visual Studio Code", kind="app", action="open_app", target=str(self.app))
        run_item(item, runner, options=self.options())
        self.assertEqual(runner.calls[0][1:], ["workspace", "C"])

    def test_a_setting_of_your_own_wins(self):
        runner = support.FakeRunner()
        run_item(self.item, runner, options=self.options(aerospace_workspaces=(("Visual Studio Code", "Q"),)))
        self.assertEqual(runner.calls[0][2], "Q")

    def test_off_means_a_plain_open(self):
        runner = support.FakeRunner()
        result = run_item(self.item, runner, options=self.options(aerospace=False))
        self.assertEqual([tuple(c) for c in runner.calls], [("open", str(self.app))])
        self.assertEqual(result.message, "opened Visual Studio Code")

    def test_an_app_without_a_rule_just_opens(self):
        other = self.tmp / "Safari.app"
        other.mkdir()
        runner = support.FakeRunner()
        run_item(Item(id="app:s", title="Safari", kind="app", action="open_app", target=str(other)), runner, options=self.options())
        self.assertEqual([c[0] for c in runner.calls], ["open"])

    def test_when_aerospace_cannot_switch_the_app_still_opens_and_the_message_says_why(self):
        class Runner(support.FakeRunner):
            def __call__(self, command, input_text=None):
                done = super().__call__(command, input_text)
                if command[1:2] == ["workspace"]:
                    done.returncode, done.stderr = 1, "Can't connect to AeroSpace server"
                return done

        runner = Runner()
        result = run_item(self.item, runner, options=self.options())
        self.assertTrue(result.ok)
        self.assertEqual(runner.calls[-1][0], "open")
        self.assertIn("could not switch to workspace C: Can't connect to AeroSpace server", result.message)

    def test_a_program_that_is_not_installed_does_not_stop_the_app(self):
        runner = support.FakeRunner()
        result = run_item(self.item, runner, options=self.options(aerospace_command="/nowhere/aerospace"))
        self.assertTrue(result.ok)
        self.assertEqual([c[0] for c in runner.calls], ["open"])
        self.assertIn("was not found", result.message)

    def test_dry_run_says_what_it_would_do_and_runs_nothing(self):
        runner = support.FakeRunner()
        result = run_item(self.item, runner, dry_run=True, options=self.options())
        self.assertEqual(runner.calls, [])
        self.assertIn("aerospace workspace C", result.message)


class Settings(support.TempDirCase):
    def test_defaults_are_off_and_validated(self):
        config = parse_config(support.good_config(), Path("x"))
        self.assertFalse(config.aerospace_enabled)
        self.assertEqual((config.screenshot_dir, config.screenshot_clipboard, config.screenshot_delay), ("auto", False, 1))
        config = parse_config(support.good_config(aerospace={"enabled": True, "workspaces": {"Zen": "B"}}), Path("x"))
        self.assertEqual((config.aerospace_enabled, config.aerospace_workspaces), (True, (("Zen", "B"),)))

    def test_bad_values_are_named(self):
        for changes, text in (
            ({"aerospace": {"enabled": "yes"}}, "aerospace.enabled"),
            ({"aerospace": {"workspaces": {"Zen": 2}}}, "aerospace.workspaces.Zen"),
            ({"screenshot": {"delay_seconds": 99}}, "screenshot.delay_seconds"),
            ({"screenshot": {"clipboard": "no"}}, "screenshot.clipboard"),
        ):
            with self.assertRaises(ConfigError) as caught:
                parse_config(support.good_config(**changes), Path("x"))
            self.assertIn(text, str(caught.exception))


class Reboot(unittest.TestCase):
    def test_reboot_asks_system_events_to_restart(self):
        runner = support.FakeRunner()
        result = run_item(Item(id="cmd:reboot", title="Reboot", kind="command", action="reboot"), runner, options=RunOptions(power_force=False))
        self.assertEqual(runner.calls[-1], ["osascript", "-e", 'tell application "System Events" to restart'])
        self.assertTrue(result.ok)


class Screenshots(support.TempDirCase):
    """The shell script is really run here, with a fake `screencapture` that records how it was called."""

    def run_script(self, region, clipboard=False, cancel=False, notify=False):
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir(exist_ok=True)
        fake = bin_dir / "screencapture"
        fake.write_text(
            '#!/bin/sh\necho "$@" > "$FAKE_ARGS"\n'
            'if [ -z "$FAKE_CANCEL" ]; then for last; do :; done; case "$last" in *.png) : > "$last";; esac; fi\n'
        )
        fake.chmod(0o755)
        folder = self.tmp / "shots dir"  # a space in the folder name on purpose
        script = screenshot_script(region, str(folder), clipboard, 1, notify, "none")
        env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE_ARGS": str(self.tmp / "args")}
        if cancel:
            env["FAKE_CANCEL"] = "1"
        done = subprocess.run(["/bin/sh", "-c", script], env=env, capture_output=True, text=True)
        args = (self.tmp / "args").read_text().strip() if (self.tmp / "args").exists() else ""
        return done, args, folder

    def test_full_screen_waits_one_second_and_saves_a_png_with_the_macos_name(self):
        done, args, folder = self.run_script(region=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(args.startswith("-x -T 1 "), args)
        files = list(folder.glob("Screenshot ????-??-?? at ??.??.??.png"))
        self.assertEqual(len(files), 1)

    def test_region_lets_the_mouse_choose_the_area(self):
        done, args, folder = self.run_script(region=True)
        self.assertTrue(args.startswith("-x -i -s "), args)
        self.assertEqual(len(list(folder.glob("*.png"))), 1)

    def test_pressing_esc_is_not_an_error_message_about_permissions(self):
        done, args, folder = self.run_script(region=True, cancel=True)
        self.assertNotEqual(done.returncode, 0)  # nothing was saved
        self.assertEqual(list(folder.glob("*.png")), [])

    def test_clipboard_mode_saves_no_file(self):
        done, args, folder = self.run_script(region=False, clipboard=True)
        self.assertIn("-c", args.split())
        self.assertFalse(folder.exists())

    def test_the_action_starts_it_in_the_background_and_does_not_wait(self):
        spawned = []
        runner = support.FakeRunner(outputs={("defaults", "read", "com.apple.screencapture", "location"): "/Users/me/Pictures/Shots\n"})
        options = RunOptions(spawn=lambda command, log: spawned.append((command, str(log))), log_dir=Path("/tmp/x"))
        result = run_item(Item(id="cmd:r", title="screenshot region", kind="command", action="screenshot_region"), runner, options=options)
        self.assertTrue(result.ok)
        self.assertEqual(spawned[0][0][:2], ["/bin/sh", "-c"])
        self.assertIn("/Users/me/Pictures/Shots", spawned[0][0][2])  # the folder macOS itself uses
        self.assertIn("-i -s", spawned[0][0][2])
        self.assertIn("Esc cancels", result.message)

    def test_a_folder_in_the_settings_beats_the_macos_one(self):
        spawned = []
        options = RunOptions(spawn=lambda c, l: spawned.append(c), screenshot_dir="/tmp/mine")
        run_item(Item(id="cmd:f", title="screenshot full_screen", kind="command", action="screenshot_full"), support.FakeRunner(), options=options)
        self.assertIn("/tmp/mine", spawned[0][2])


class Commands(CliCase):
    def setUp(self):
        super().setUp()
        self.cfg = support.good_config(
            [self.tmp / "Applications"],
            commands=[
                {"id": "reboot", "title": "Reboot", "action": "reboot", "keywords": ["restart"], "confirm": True},
                {"id": "screenshot_full_screen", "title": "screenshot full_screen", "action": "screenshot_full", "keywords": ["screenshot"]},
                {"id": "screenshot_region", "title": "screenshot region", "action": "screenshot_region", "keywords": ["screenshot"]},
            ],
        )
        self.config = str(self.write_config(self.cfg))

    def titles(self, text):
        code, out, _ = self.call("search", text, "--json")
        return [r["title"] for r in json.loads(out)["results"]]

    def test_typing_screenshot_lists_the_two_options(self):
        self.assertEqual(self.titles("screenshot")[:2], ["screenshot full_screen", "screenshot region"])

    def test_typing_the_option_narrows_it_down(self):
        self.assertEqual(self.titles("screenshot reg")[0], "screenshot region")
        self.assertEqual(self.titles("screenshot full")[0], "screenshot full_screen")

    def test_reboot_asks_for_confirmation(self):
        code, out, _ = self.call("run", "--id", "cmd:reboot", answers=["n"])
        self.assertNotEqual(code, 0)
        self.assertEqual(self.runner.calls, [])
        code, out, _ = self.call("run", "--id", "cmd:reboot", "--yes")
        self.assertIn("to restart", self.spawned[0][0][2])

    def test_a_screenshot_runs_through_the_cli_without_asking(self):
        code, out, _ = self.call("run", "--id", "cmd:screenshot_region", "--json")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.spawned), 1)


class HelpScreenshot(unittest.TestCase):
    def rows(self):
        config = parse_config(support.good_config(), Path("x"))
        return myhelp.screenshot_rows(config, support.FakeRunner())[0]

    def test_the_topic_exists_and_has_synonyms(self):
        self.assertIn("screenshot", myhelp.TOPICS)
        for word in ("screenshots", "screen", "capture"):
            self.assertEqual(myhelp.SYNONYMS[word], "screenshot")

    def test_it_lists_the_macos_shortcuts(self):
        titles = [r.title for r in self.rows()]
        for shortcut in ("⇧⌘3", "⇧⌘4", "⇧⌘5"):
            self.assertIn(shortcut, titles)
        text = " ".join(r.detail for r in self.rows())
        self.assertIn("⌃⇧⌘3", text)  # with Control: to the clipboard
        self.assertIn("Space", text)  # window mode

    def test_it_explains_the_two_launcher_commands_and_the_permission(self):
        titles = [r.title for r in self.rows()]
        self.assertIn("screenshot full_screen", titles)
        self.assertIn("screenshot region", titles)
        self.assertTrue(any("Screen Recording" in r.subtitle or "Screen Recording" in r.detail for r in self.rows()))


class PowerSequence(support.TempDirCase):
    """reboot / shutdown even when something refuses to quit (mypower.py)."""

    PS = ("ps", "-axo", "pid=,command=")
    PGREP = ("pgrep", "-f", "mylauncher_app.py")

    def setUp(self):
        super().setUp()
        listing = (
            "  500 /Applications/Ghostty.app/Contents/MacOS/ghostty\n"
            "  501 /Applications/Visual Studio Code.app/Contents/MacOS/Electron\n"
            "  777 /opt/homebrew/Cellar/python@3.13/3.13.1/Frameworks/Python.framework/Versions/3.13/Resources/Python.app/Contents/MacOS/Python app/mylauncher_app.py\n"
        )
        self.runner = support.FakeRunner(outputs={self.PS: listing, self.PGREP: "777\n888\n"})
        self.spawned = []
        self.item = Item(id="cmd:reboot", title="Reboot", kind="command", action="reboot")

    def options(self, **changes):
        base = dict(spawn=lambda c, l: self.spawned.append((c, str(l))), power_lock=self.tmp / "power.lock", log_dir=self.tmp)
        return RunOptions(**{**base, **changes})

    def test_every_app_is_closed_politely_then_force_quit_then_the_restart(self):
        result = run_item(self.item, self.runner, options=self.options())
        self.assertTrue(result.ok)
        script = self.spawned[0][0][2]
        self.assertIn('tell application "/Applications/Ghostty.app" to quit', script)  # polite first
        self.assertIn("kill -KILL 500", script)  # Ghostty with btop/ssh running: refused, so it is force quit
        self.assertIn("kill -KILL 501", script)
        self.assertNotIn("777", script)  # the launcher itself is never in the list (protected: python)
        self.assertLess(script.index("quit"), script.index("sleep 8"))
        self.assertLess(script.index("kill -KILL 500"), script.index("to restart"))  # the restart comes LAST
        self.assertTrue(script.rstrip().endswith("tell application \"System Events\" to restart'"))

    def test_the_other_copies_of_the_launcher_are_killed_first(self):
        run_item(self.item, self.runner, options=self.options())
        kills = [c for c in self.runner.calls if c[:2] == ["kill", "-KILL"]]
        self.assertEqual(len(kills), 1)
        self.assertIn("888", kills[0])  # 777 is... also another copy here (the test's parent is not 777): both are listed
        self.assertTrue(set(kills[0][2:]) <= {"777", "888"})

    def test_a_second_request_within_two_minutes_is_refused(self):
        self.assertTrue(run_item(self.item, self.runner, options=self.options()).ok)
        again = run_item(self.item, self.runner, options=self.options())
        self.assertFalse(again.ok)
        self.assertIn("already requested", again.message)
        self.assertEqual(len(self.spawned), 1)

    def test_an_old_marker_does_not_block(self):
        import time
        lock = self.tmp / "power.lock"
        lock.write_text("1")
        old = time.time() - 600
        os.utime(lock, (old, old))
        self.assertTrue(run_item(self.item, self.runner, options=self.options()).ok)

    def test_force_off_only_removes_copies_and_asks_politely(self):
        result = run_item(self.item, self.runner, options=self.options(power_force=False))
        self.assertTrue(result.ok)
        self.assertEqual(self.spawned, [])
        self.assertEqual(self.runner.calls[-1][0], "osascript")

    def test_dry_run_touches_nothing(self):
        runner = support.FakeRunner()
        result = run_item(self.item, runner, dry_run=True, options=self.options())
        self.assertEqual((runner.calls, self.spawned), ([], []))
        self.assertFalse((self.tmp / "power.lock").exists())
        self.assertIn("force quit after 8 s", result.message)

    def test_script_syntax_is_valid_shell(self):
        import mypower
        from mykill import RunningApp
        script = mypower.power_script([RunningApp('My "App"', '/Applications/My "App".app', (5, 6))], True, 3, ["echo", "restart now"])
        done = subprocess.run(["/bin/sh", "-n", "-c", script], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)


class OneCopyOnly(support.TempDirCase):
    def test_the_second_copy_finds_the_lock_and_names_the_first(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
        import myinstance
        first, _ = myinstance.acquire(self.tmp / "app.lock")
        self.assertIsNotNone(first)
        second, other = myinstance.acquire(self.tmp / "app.lock")
        self.assertIsNone(second)
        self.assertEqual(other, str(os.getpid()))
        first.close()  # the first copy ends: the lock is free again
        third, _ = myinstance.acquire(self.tmp / "app.lock")
        self.assertIsNotNone(third)
        third.close()


class QuitRequests(unittest.TestCase):
    def test_a_quit_during_a_power_off_is_accepted_and_otherwise_ignored(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
        import mylauncher_app

        class Root:
            def __init__(self): self.quits, self.commands = 0, {}
            def protocol(self, *a): pass
            def createcommand(self, name, func): self.commands[name] = func
            def quit(self): self.quits += 1

        window = type("W", (), {"hide": lambda self: None})()
        for allowed, expected in ((False, 0), (True, 1)):
            root = Root()
            lines = []
            mylauncher_app.protect_from_closing(root, window, log=lines.append, may_quit=lambda: allowed)
            root.commands["::tk::mac::Quit"]()
            self.assertEqual(root.quits, expected)
