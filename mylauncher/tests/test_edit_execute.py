"""Step 8: the `edit` command (conf/edit.json) and the `execute` command (conf/execute.json)."""

import json
import unittest
from pathlib import Path

import support
from test_cli import CliCase
from myactions import RunOptions, execute_background, execute_terminal, edit_file
from myconfig import ConfigError, parse_config
from myedit import expand, parse_edit, split_description
from myexecute import background_script, parse_execute, plain, source_prefix, terminal_script
from mytypes import Item


class EditExecuteCase(CliCase):
    def put(self, name, data):
        (self.tmp / name).write_text(json.dumps(data), encoding="utf-8")

    def configure(self, **sections):
        """Rewrite the configuration with extra sections (edit / execute)."""
        self.config = str(self.write_config(support.good_config([self.tmp / "Applications"], **sections)))

    def search(self, text):
        code, out, _ = self.call("search", text, "--json")
        return json.loads(out)

    def titles(self, text):
        return [r["title"] for r in self.search(text)["results"]]


class Parsing(unittest.TestCase):
    def test_name_comes_from_the_description_before_the_comma(self):
        self.assertEqual(split_description("AeroSpace, an i3-like tiling window manager"), ("AeroSpace", "an i3-like tiling window manager"))
        self.assertEqual(split_description("zsh aliases"), ("zsh aliases", ""))

    def test_edit_entries(self):
        (a, b) = parse_edit([
            {"description": "AeroSpace, a tiling manager", "emoji": "🪟", "path": "~/a.toml"},
            {"name": "notes", "description": "my notes, daily", "path": "/n"},
        ])
        self.assertEqual((a.name, a.description, a.emoji, a.path), ("AeroSpace", "a tiling manager", "🪟", "~/a.toml"))
        self.assertEqual((b.name, b.description, b.emoji), ("notes", "my notes, daily", ""))  # an explicit name keeps the whole description

    def test_edit_errors_name_the_entry(self):
        for data, text in (
            ({}, "must be a list"),
            ([3], r"edit.json\[0\] must be an object"),
            ([{"path": "/x"}], r"edit.json\[0\] needs a description"),
            ([{"description": "a"}], r"edit.json\[0\].path"),
            ([{"description": "a", "path": 3}], r"\.path"),
            ([{"description": 3, "path": "/x"}], r"\.description must be text"),
            ([{"description": "a", "emoji": 1, "path": "/x"}], r"\.emoji must be text"),
        ):
            with self.subTest(data=data), self.assertRaisesRegex(ConfigError, text):
                parse_edit(data)

    def test_execute_entries_and_errors(self):
        (e,) = parse_execute([{"description": "shutdown my computer", "command": " shutdown mac --now ", "confirm": True, "terminal": False}])
        self.assertEqual((e.name, e.command, e.confirm, e.terminal), ("shutdown my computer", "shutdown mac --now", True, False))
        self.assertIsNone(parse_execute([{"description": "x", "command": "y"}])[0].terminal)  # "use the default"
        for data, text in (
            ([{"description": "x"}], r"\.command must be text"),
            ([{"description": "x", "command": "  "}], r"\.command"),
            ([{"description": "x", "command": "y", "terminal": "yes"}], r"\.terminal must be true or false"),
            ([{"description": "x", "command": "y", "confirm": 1}], r"\.confirm must be true or false"),
            ([{"command": "y"}], "needs a description"),
        ):
            with self.subTest(data=data), self.assertRaisesRegex(ConfigError, text):
                parse_execute(data)


class Expanding(support.TempDirCase):
    def test_plain_path_is_kept_even_if_missing(self):
        (label, path), = expand(parse_edit([{"description": "a", "path": str(self.tmp / "nope.txt")}])[0])
        self.assertEqual((label, path), ("", self.tmp / "nope.txt"))

    def test_wildcards_give_one_row_per_existing_file_hidden_ones_skipped(self):
        for name in ("base.yml", "sub/more.yml", ".hidden/secret.yml", "sub/.dot.yml", "notes.txt"):
            file = self.tmp / "esp" / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("x")
        entry = parse_edit([{"description": "espanso", "path": f"{self.tmp}/esp/**/*.yml"}])[0]
        self.assertEqual([label for label, _ in expand(entry)], ["base.yml", "more.yml"])

    def test_skill_files_are_labelled_with_their_folder(self):
        for skill in ("docs", "slides"):
            (self.tmp / "skills" / skill).mkdir(parents=True)
            (self.tmp / "skills" / skill / "SKILL.md").write_text("x")
        entry = parse_edit([{"description": "skills", "path": f"{self.tmp}/skills/**/SKILL.md"}])[0]
        self.assertEqual([label for label, _ in expand(entry)], ["docs", "slides"])

    def test_tilde_is_expanded(self):
        (label, path), = expand(parse_edit([{"description": "a", "path": "~/x.txt"}])[0])
        self.assertTrue(path.is_absolute())


class EditSearch(EditExecuteCase):
    def setUp(self):
        super().setUp()
        (self.tmp / "aero.toml").write_text("x")
        (self.tmp / "skills" / "docs").mkdir(parents=True)
        (self.tmp / "skills" / "docs" / "SKILL.md").write_text("x")
        self.put("edit.json", [
            {"description": "AeroSpace, an i3-like tiling window manager", "emoji": "🪟", "path": str(self.tmp / "aero.toml")},
            {"description": "skills, OpenClaw skills", "emoji": "🧠", "path": f"{self.tmp}/skills/**/SKILL.md"},
            {"description": "ghost, a file that is not there yet", "path": str(self.tmp / "ghost.txt")},
        ])
        self.configure()

    def test_edit_lists_everything_in_file_order(self):
        data = self.search("edit")
        self.assertEqual((data["mode"], data["highlight"]), ("edit", 4))
        self.assertEqual([r["title"] for r in data["results"]], ["AeroSpace", "skills · docs", "ghost"])

    def test_tab_keeps_the_word(self):
        self.assertEqual(self.search("edit aero")["completion"], "edit AeroSpace")
        self.assertEqual(self.search("edit openclaw")["completion"], "edit skills · docs")
        self.assertEqual(self.search("edit skills · docs")["results"][0]["title"], "skills · docs")  # what Tab wrote finds it again

    def test_rows_have_emoji_description_and_path(self):
        rows = {r["title"]: r for r in self.search("edit")["results"]}
        row = rows["AeroSpace"]
        self.assertEqual((row["icon"], row["badge"], row["kind"], row["action"]), ("🪟", "File", "edit", "edit_file"))
        self.assertIn("an i3-like tiling window manager", row["subtitle"])
        self.assertIn("aero.toml", row["subtitle"])
        self.assertEqual(rows["skills · docs"]["icon"], "🧠")
        self.assertEqual(rows["ghost"]["icon"], "📝")  # the default for the kind
        self.assertEqual(rows["ghost"]["badge"], "Missing")
        self.assertIn("(not found)", rows["ghost"]["subtitle"])

    def test_filtering_by_name_description_or_path(self):
        self.assertEqual(self.titles("edit aero"), ["AeroSpace"])
        self.assertEqual(self.titles("edit tiling"), ["AeroSpace"])  # a word of the description
        self.assertEqual(self.titles("edit openclaw"), ["skills · docs"])
        self.assertEqual(self.titles("edit zzz"), [])

    def test_the_hint_is_found_while_typing_the_word(self):
        data = self.search("ed")
        self.assertEqual(data["mode"], "normal")
        self.assertIn("prefix:edit", [r["id"] for r in data["results"]])

    def test_enter_opens_the_file_in_the_editor(self):
        code, out, _ = self.call("run", "--id", f"edit:AeroSpace:{self.tmp / 'aero.toml'}", "--text=edit aero", "--yes", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(self.runner.calls[-1], ["open", "-a", "Visual Studio Code", str(self.tmp / "aero.toml")])

    def test_run_by_words(self):
        code, _, _ = self.call("run", "edit", "aero", "--yes")
        self.assertEqual(code, 0)
        self.assertEqual(self.runner.calls[-1][-1], str(self.tmp / "aero.toml"))

    def test_editor_from_the_configuration(self):
        self.configure(edit={"editor": "TextEdit"})
        self.call("run", "edit", "aero", "--yes")
        self.assertEqual(self.runner.calls[-1][:3], ["open", "-a", "TextEdit"])
        self.configure(edit={"editor": ["nvim", "{path}"]})
        self.call("run", "edit", "aero", "--yes")
        self.assertEqual(self.runner.calls[-1], ["nvim", str(self.tmp / "aero.toml")])

    def test_a_missing_file_is_not_opened(self):
        code, out, _ = self.call("run", "edit", "ghost", "--yes", "--json")
        self.assertNotEqual(code, 0)
        self.assertIn("file not found", out)
        self.assertEqual(self.runner.calls, [])


class EditorAction(support.TempDirCase):
    def item(self):
        (self.tmp / "f.txt").write_text("x")
        return Item("edit:f", "f", "edit", "edit_file", target=str(self.tmp / "f.txt"))

    def test_fallback_to_the_default_text_editor_when_the_editor_fails(self):
        results = iter([1, 0])  # `open -a Missing` fails, `open -t` works

        def runner(command, input_text=None):
            return support.FakeRunner(returncode=next(results))(command)

        result = edit_file(self.item(), runner=runner)
        self.assertTrue(result.ok)
        self.assertEqual(result.command[:2], ["open", "-t"])
        self.assertIn("did not work", result.message)

    def test_fallback_when_the_program_does_not_exist(self):
        calls = []

        def runner(command, input_text=None):
            calls.append(command)
            if command[0] == "nvim":
                raise FileNotFoundError
            return support.FakeRunner()(command)

        self.assertTrue(edit_file(self.item(), runner=runner, options=RunOptions(editor_command=("nvim", "{path}"))).ok)
        self.assertEqual(calls[-1][:2], ["open", "-t"])

    def test_dry_run_runs_nothing_and_does_not_need_the_file(self):
        runner = support.FakeRunner()
        item = Item("edit:g", "g", "edit", "edit_file", target="/nonexistent/g.txt")
        result = edit_file(item, runner=runner, dry_run=True)
        self.assertTrue(result.ok)
        self.assertEqual(runner.calls, [])
        self.assertIn("Visual Studio Code", result.message)


class ExecuteSearch(EditExecuteCase):
    def setUp(self):
        super().setUp()
        self.put("execute.json", [
            {"description": "help, my help script", "emoji": "📚", "command": "sh ~/macOS/scripts/help.sh -all", "terminal": True},
            {"description": "shutdown my computer", "emoji": "🔌", "command": "shutdown mac --now", "confirm": True},
            {"description": "content_creation, check & improve a Hugo page", "command": "content_creation"},
        ])
        self.configure()

    def test_execute_lists_the_commands(self):
        data = self.search("execute")
        self.assertEqual((data["mode"], data["highlight"]), ("execute", 7))
        self.assertEqual([r["title"] for r in data["results"]], ["help", "shutdown my computer", "content_creation"])

    def test_tab_keeps_the_word(self):
        data = self.search("execute")
        self.assertEqual(data["completion"], "execute help")  # not "help": Tab must not replace the word
        self.assertEqual(self.search("execute shut")["completion"], "execute shutdown my computer")

    def test_rows(self):
        rows = {r["title"]: r for r in self.search("execute")["results"]}
        self.assertEqual((rows["help"]["icon"], rows["help"]["badge"], rows["help"]["action"]), ("📚", "Terminal", "execute_terminal"))
        self.assertIn("my help script", rows["help"]["subtitle"])
        self.assertIn("sh ~/macOS/scripts/help.sh -all", rows["help"]["subtitle"])
        self.assertEqual((rows["shutdown my computer"]["badge"], rows["shutdown my computer"]["confirm"]), ("Background", True))
        self.assertEqual(rows["content_creation"]["icon"], "▶️")

    def test_filter(self):
        self.assertEqual(self.titles("execute hugo"), ["content_creation"])
        self.assertEqual(self.titles("execute shut"), ["shutdown my computer"])

    def test_default_terminal_setting_applies_to_entries_that_do_not_say(self):
        self.configure(execute={"terminal": True})
        rows = {r["title"]: r for r in self.search("execute")["results"]}
        self.assertEqual(rows["content_creation"]["action"], "execute_terminal")

    def test_a_background_command_is_spawned_with_the_zsh_script(self):
        code, out, _ = self.call("run", "execute", "content", "--yes", "--json")
        self.assertEqual(code, 0)
        (command, log), = self.spawned
        self.assertEqual(command[:2], ["/bin/zsh", "-lc"])
        self.assertIn("content_creation", command[2])
        self.assertIn(".zsh_functions", command[2])  # the functions file is loaded first
        self.assertTrue(log.endswith("content_creation.log"))
        self.assertEqual(self.runner.calls, [])  # nothing waited for

    def test_a_terminal_command_goes_through_the_terminal_command(self):
        code, _, _ = self.call("run", "execute", "help", "--yes")
        self.assertEqual(code, 0)
        command = self.runner.calls[-1]
        self.assertEqual(command[:4], ["open", "-na", "Ghostty", "--args"])
        self.assertIn("help.sh -all", command[-1])
        self.assertIn("Press Enter to close", command[-1])
        self.assertEqual(self.spawned, [])

    def test_the_dangerous_one_asks_first(self):
        code, _, _ = self.call("run", "execute", "shutdown", answers=["n"])
        self.assertNotEqual(code, 0)
        self.assertEqual(self.spawned, [])
        code, _, _ = self.call("run", "execute", "shutdown", answers=["y"])
        self.assertEqual(code, 0)
        self.assertEqual(len(self.spawned), 1)

    def test_dry_run_shows_the_command_and_starts_nothing(self):
        code, out, _ = self.call("run", "execute", "content", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("content_creation", out)
        self.assertEqual((self.spawned, self.runner.calls), ([], []))


class ExecuteActions(support.TempDirCase):
    ITEM = Item("execute:x", "my script", "execute", "execute_background", target="echo hi; echo there")

    def test_background_script_runs_in_a_subshell_notifies_and_keeps_the_exit_code(self):
        script = background_script("my script", "echo hi", ("~/.zsh_functions",))
        self.assertTrue(script.startswith("( [ -f "))
        self.assertIn("echo hi\n)", script)  # a trailing comment in the command cannot swallow the closing parenthesis
        self.assertIn('code=$?', script)
        self.assertIn("display notification", script)
        self.assertIn("mylauncher: my script", script)
        self.assertTrue(script.endswith('exit "$code"'))
        self.assertNotIn("osascript", background_script("x", "y", (), notify=False))

    def test_names_cannot_break_out_of_the_quotes(self):
        self.assertEqual(plain('a"b\\c$d`e'), "abcde")
        script = background_script('evil"; rm -rf ~; "', "true", ())
        self.assertNotIn('evil"', script)

    def test_source_prefix_quotes_paths_and_ignores_missing_files(self):
        prefix = source_prefix(["~/my functions"])
        self.assertIn("[ -f ", prefix)
        self.assertIn("'", prefix)  # a path with a space is quoted
        self.assertEqual(source_prefix([]), "")

    def test_terminal_script_waits_for_enter(self):
        script = terminal_script("ls", ())
        self.assertIn("read", script.splitlines())
        self.assertIn("exit code $code", script)

    def test_background_spawn_gets_the_log_path_and_reports_it(self):
        spawned = []
        options = RunOptions(log_dir=self.tmp / "logs", spawn=lambda command, log: spawned.append((command, log)))
        result = execute_background(self.ITEM, options=options)
        self.assertTrue(result.ok)
        self.assertEqual(spawned[0][1], self.tmp / "logs" / "my_script.log")
        self.assertIn("my_script.log", result.message)

    def test_spawn_failure_is_reported(self):
        def boom(command, log):
            raise PermissionError("no")

        result = execute_background(self.ITEM, options=RunOptions(spawn=boom))
        self.assertFalse(result.ok)
        self.assertIn("could not start", result.message)

    def test_terminal_failure_falls_back_to_the_background(self):
        spawned = []
        options = RunOptions(spawn=lambda command, log: spawned.append(command), log_dir=self.tmp)
        for runner in (support.FakeRunner(returncode=1), support.FakeRunner(error=FileNotFoundError())):
            spawned.clear()
            result = execute_terminal(self.ITEM, runner=runner, options=options)
            self.assertTrue(result.ok)
            self.assertEqual(len(spawned), 1)
            self.assertIn("terminal command did not work", result.message)

    def test_the_real_default_spawn_starts_a_program_and_writes_its_log(self):
        import sys
        import time
        from myactions import default_spawn

        log = self.tmp / "out" / "run.log"
        default_spawn([sys.executable, "-c", "print('hello from the child')"], log)
        for _ in range(100):  # the child runs on its own: wait for it a little
            if log.exists() and "hello" in log.read_text():
                break
            time.sleep(0.05)
        self.assertIn("hello from the child", log.read_text())


class ConfigSections(unittest.TestCase):
    def parse(self, **sections):
        return parse_config(support.good_config(**sections), Path("/x/conf/myconfiguration.json"))

    def test_defaults(self):
        c = self.parse()
        self.assertEqual((c.edit_word, c.execute_word), ("edit", "execute"))
        self.assertEqual(c.edit_path, Path("/x/conf/edit.json"))  # next to the configuration
        self.assertEqual(c.edit_editor, ("open", "-a", "Visual Studio Code", "{path}"))
        self.assertEqual((c.execute_shell, c.execute_terminal), (("/bin/zsh", "-lc"), False))

    def test_editor_forms(self):
        self.assertEqual(self.parse(edit={"editor": "TextEdit"}).edit_editor, ("open", "-a", "TextEdit", "{path}"))
        self.assertEqual(self.parse(edit={"editor": ["code", "{path}"]}).edit_editor, ("code", "{path}"))
        for bad in (["nvim"], [], 3, ""):
            with self.subTest(bad=bad), self.assertRaisesRegex(ConfigError, "edit.editor"):
                self.parse(edit={"editor": bad})

    def test_execute_settings(self):
        c = self.parse(execute={"shell": ["/bin/bash", "-c"], "source": [], "terminal": True, "notify": False, "file": "/abs/e.json"})
        self.assertEqual((c.execute_shell, c.execute_source, c.execute_terminal, c.execute_notify, c.execute_path), (("/bin/bash", "-c"), (), True, False, Path("/abs/e.json")))
        with self.assertRaisesRegex(ConfigError, "execute.shell"):
            self.parse(execute={"shell": []})
        with self.assertRaisesRegex(ConfigError, "execute.terminal_command"):
            self.parse(execute={"terminal_command": ["open", "Ghostty"]})

    def test_the_five_words_must_all_differ(self):
        with self.assertRaisesRegex(ConfigError, "must all be different"):
            self.parse(edit={"word": "help"})
        with self.assertRaisesRegex(ConfigError, "must all be different"):
            self.parse(execute={"word": "run"})
        with self.assertRaisesRegex(ConfigError, "edit.word"):
            self.parse(edit={"word": "two words"})


class Favorites(EditExecuteCase):
    """Step 20.17: `favorites` = your short list (conf/favorites.json), built on the `execute` machinery."""

    LIST = [
        {"description": "shutdown, switch off the three computers", "emoji": "🔌", "command": "shutdownmac --now", "terminal": True, "confirm": True},
        {"description": "content_creation, check and improve a Hugo page", "emoji": "✍️", "command": "content_creation", "terminal": True},
        {"description": "prayer_website, publish today's prayer", "emoji": "🌐", "command": "bash ~/macOS/mylauncher/cli/ml daily-gospel-post", "terminal": True, "confirm": True},
        {"description": "prayer_facebook, today's prayer as a Facebook post", "emoji": "📘", "command": "bash ~/macOS/mylauncher/cli/ml daily-gospel-facebook", "terminal": True},
    ]

    def setUp(self):
        super().setUp()
        self.put("favorites.json", self.LIST)
        self.put("execute.json", [{"description": "other, not a favorite", "command": "true"}])
        self.configure()

    def test_the_word_lists_the_favorites_in_the_order_of_the_file(self):
        data = self.search("favorites")
        self.assertEqual((data["mode"], data["highlight"]), ("favorites", 9))
        self.assertEqual([r["title"] for r in data["results"]], ["shutdown", "content_creation", "prayer_website", "prayer_facebook"])
        self.assertNotIn("other", [r["title"] for r in data["results"]])  # execute.json is a different list

    def test_rows_ids_badges_and_tab(self):
        rows = {r["title"]: r for r in self.search("favorites")["results"]}
        self.assertEqual(rows["shutdown"]["id"], "favorites:shutdown")
        self.assertEqual((rows["shutdown"]["icon"], rows["shutdown"]["badge"], rows["shutdown"]["confirm"], rows["shutdown"]["action"]),
                         ("🔌", "Terminal", True, "execute_terminal"))
        self.assertFalse(rows["prayer_facebook"]["confirm"])
        self.assertEqual(self.search("favorites")["completion"], "favorites shutdown")  # Tab keeps the word
        self.assertEqual(self.search("favorites cont")["completion"], "favorites content_creation")

    def test_filter(self):
        self.assertEqual(sorted(self.titles("favorites prayer")), ["prayer_facebook", "prayer_website"])  # both; the order between equal matches is not promised
        self.assertEqual(self.titles("favorites facebook"), ["prayer_facebook"])

    def test_the_hint_row_is_found_by_typing_part_of_the_word(self):
        self.assertIn("Favorites (favorites)", self.titles("favor"))

    def test_the_shutdown_asks_first_and_runs_nothing_when_you_say_no(self):
        code, _, _ = self.call("run", "favorites", "shutdown", answers=["n"])
        self.assertNotEqual(code, 0)
        self.assertEqual((self.spawned, self.runner.calls), ([], []))
        code, _, _ = self.call("run", "favorites", "shutdown", answers=["y"])
        self.assertEqual(code, 0)
        command = self.runner.calls[-1]
        self.assertEqual(command[:4], ["open", "-na", "Ghostty", "--args"])
        self.assertIn("shutdownmac --now", command[-1])
        self.assertIn(".zsh_functions", command[-1])  # your functions file is loaded first: that is where shutdownmac lives

    def test_a_list_word_alone_never_runs_the_first_entry(self):
        for word in ("favorites", "execute"):
            with self.subTest(word=word):
                code, out, err = self.call("run", word, "--yes")
                self.assertEqual(code, 2)
                self.assertIn("say which one", err + out)
                self.assertEqual((self.spawned, self.runner.calls), ([], []))

    def test_dry_run_shows_the_command_and_starts_nothing(self):
        code, out, _ = self.call("run", "favorites", "content", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("content_creation", out)
        self.assertEqual((self.spawned, self.runner.calls), ([], []))

    def test_the_prayer_favorites_call_the_real_ml_subcommands(self):
        import mylauncher as M
        names = [a for a in M.make_parser()._actions if a.__class__.__name__ == "_SubParsersAction"][0].choices
        for entry in self.LIST[2:]:
            self.assertIn(entry["command"].split()[-1], names)  # daily-gospel-post / daily-gospel-facebook exist (underscores would not)

    def test_the_shipped_list_has_the_four_favorites(self):
        from myexecute import load_execute
        root = Path(__file__).resolve().parent.parent
        for where in ("conf", "defaults"):
            entries = load_execute(root / where / "favorites.json")
            self.assertEqual([e.name for e in entries], ["shutdown", "content_creation", "prayer_website", "prayer_facebook"], where)
            self.assertEqual([e.confirm for e in entries], [True, False, True, False], where)
            self.assertTrue(all(e.terminal for e in entries), where)

    def test_the_word_cannot_clash_with_another(self):
        self.configure(favorites={"word": "execute"})
        code, out, err = self.call("search", "x")
        self.assertEqual(code, 2)
        self.assertIn("different words", err + out)

    def test_a_missing_file_means_an_empty_list_and_doctor_reports_it(self):
        (self.tmp / "favorites.json").unlink()
        self.assertEqual(self.titles("favorites"), [])
        code, out, _ = self.call("doctor")
        self.assertIn("favorites: 0 entries", out)
        self.assertIn("file not found", out)

    def test_a_mistake_in_the_file_names_it(self):
        self.put("favorites.json", [{"description": "x"}])
        code, out, err = self.call("search", "x")
        self.assertEqual(code, 2)
        self.assertIn("favorites.json[0]", err + out)

    def test_help_has_the_word(self):
        code, out, _ = self.call("help", "launcher")
        self.assertIn("favorites", out)  # (the GUI / CLI / Example lines of every word are checked by DocsStayComplete in test_step19)


class FilesAndDoctor(EditExecuteCase):
    def test_bad_json_names_the_file(self):
        (self.tmp / "edit.json").write_text("[{", encoding="utf-8")
        code, out, err = self.call("search", "x")
        self.assertEqual(code, 2)
        self.assertIn("edit.json", err + out)

    def test_a_quicklink_cannot_use_the_new_words(self):
        self.put("quicklinks.json", [{"keyword": "edit", "url": "https://x.test/{query}"}])
        code, out, err = self.call("search", "x")
        self.assertEqual(code, 2)
        self.assertIn("reserved", err + out)

    def test_doctor_reports_both_files_the_editor_and_missing_files(self):
        self.put("edit.json", [{"description": "ghost, nothing here", "path": str(self.tmp / "ghost")}])
        self.put("execute.json", [{"description": "a", "command": "b"}])
        code, out, _ = self.call("doctor")
        self.assertIn("edit: 1 entry", out)
        self.assertIn("execute: 1 entry", out)
        self.assertIn("editor: Visual Studio Code", out)
        self.assertIn("1 file(s) do not exist: ghost", out)

    def test_help_launcher_lists_the_new_words(self):
        code, out, _ = self.call("help", "launcher")
        self.assertIn("edit", out)
        self.assertIn("execute", out)


if __name__ == "__main__":
    unittest.main()
