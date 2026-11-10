"""mylauncher.py: the command line, end to end (fake apps, fake runner)."""

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout

import support
import mylauncher as M


class CliCase(support.TempDirCase):
    def setUp(self):
        super().setUp()
        folder = self.make_apps("Applications", "Obsidian", "Safari", "Zen", "Visual Studio Code")
        self.config = str(self.write_config(support.good_config([folder])))
        self.runner = support.FakeRunner()

    def call(self, *args, answers=(), runner=None):
        """Run the CLI; return (exit code, stdout, stderr)."""
        answers = iter(answers)

        def ask(prompt):
            try:
                return next(answers)
            except StopIteration:
                raise EOFError from None

        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = M.main([*args, "--config", self.config], runner=runner or self.runner, ask=ask)
        return code, out.getvalue(), err.getvalue()


class Listing(CliCase):
    def test_list_json(self):
        code, out, _ = self.call("list", "--json")
        ids = [i["id"] for i in json.loads(out)]
        self.assertEqual(code, 0)
        self.assertEqual(ids[0], "cmd:shutdown")
        self.assertIn("app:Obsidian", ids)
        self.assertEqual(len(ids), 5)

    def test_list_text(self):
        code, out, _ = self.call("list")
        self.assertIn("Run Obsidian", out)
        self.assertIn("5 item(s)", out)


class Searching(CliCase):
    def test_search_json_has_results_and_completion(self):
        code, out, _ = self.call("search", "OBS", "--json")
        data = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(data["query"], "OBS")
        self.assertEqual(data["completion"], "run obsidian")
        self.assertEqual([r["id"] for r in data["results"]], ["app:Obsidian"])
        self.assertEqual(data["results"][0]["score"], 60)

    def test_search_without_words_lists_everything_up_to_the_limit(self):
        _, out, _ = self.call("search", "--json", "--limit", "2")
        self.assertEqual(len(json.loads(out)["results"]), 2)

    def test_limit_comes_from_the_configuration_by_default(self):
        data = support.good_config()
        data["search"]["max_results"] = 1
        data["apps"]["folders"] = [str(self.tmp / "Applications")]
        self.config = str(self.write_config(data))
        _, out, _ = self.call("search", "--json")
        self.assertEqual(len(json.loads(out)["results"]), 1)

    def test_no_match_is_exit_1(self):
        code, out, _ = self.call("search", "qqq")
        self.assertEqual(code, 1)
        self.assertIn("no match", out)

    def test_several_words(self):
        _, out, _ = self.call("search", "run", "obs", "--json")
        self.assertEqual(json.loads(out)["query"], "run obs")

    def test_complete(self):
        code, out, _ = self.call("complete", "saf")
        self.assertEqual((code, out.strip()), (0, "run safari"))


class Running(CliCase):
    def test_run_best_match(self):
        code, out, _ = self.call("run", "obs")
        self.assertEqual(code, 0)
        self.assertEqual(self.runner.calls[0][0], "open")
        self.assertTrue(self.runner.calls[0][1].endswith("Obsidian.app"))

    def test_run_by_id(self):
        code, _, _ = self.call("run", "--id", "app:Zen")
        self.assertEqual(code, 0)
        self.assertTrue(self.runner.calls[0][1].endswith("Zen.app"))

    def test_dry_run(self):
        code, out, _ = self.call("run", "obs", "--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(self.runner.calls, [])
        self.assertIn("dry run", out)

    def test_unknown_id_and_no_match(self):
        self.assertEqual(self.call("run", "--id", "app:Nope")[0], 1)
        self.assertEqual(self.call("run", "qqq")[0], 1)
        self.assertEqual(self.runner.calls, [])

    def test_run_without_anything_to_run(self):
        code, _, err = self.call("run")
        self.assertEqual(code, 2)
        self.assertIn("say what to run", err)

    def test_failing_command_is_exit_1(self):
        code, out, _ = self.call("run", "obs", runner=support.FakeRunner(returncode=1, stderr="boom"))
        self.assertEqual(code, 1)
        self.assertIn("boom", out)


class Confirmation(CliCase):
    def test_shutdown_asks_and_no_means_nothing_happens(self):
        code, out, _ = self.call("run", "shutdown", answers=["n"])
        self.assertEqual(code, 1)
        self.assertIn("cancelled", out)
        self.assertEqual(self.runner.calls, [])

    def test_empty_answer_is_no(self):
        self.assertEqual(self.call("run", "shutdown", answers=[""])[0], 1)
        self.assertEqual(self.runner.calls, [])

    def test_no_one_to_answer_is_no(self):
        self.assertEqual(self.call("run", "shutdown")[0], 1)  # answers exhausted -> EOFError
        self.assertEqual(self.runner.calls, [])

    def test_yes_shuts_down(self):
        for answer in ("y", "YES"):
            self.runner.calls.clear()
            with self.subTest(answer=answer):
                code, _, _ = self.call("run", "shutdown", answers=[answer])
                self.assertEqual(code, 0)
                self.assertEqual(self.runner.calls[0][0], "osascript")

    def test_dash_dash_yes_skips_the_question(self):
        code, _, _ = self.call("run", "--id", "cmd:shutdown", "--yes")
        self.assertEqual(code, 0)
        self.assertEqual(self.runner.calls[0][0], "osascript")

    def test_dry_run_does_not_ask(self):
        code, out, _ = self.call("run", "shutdown", "--dry-run")
        self.assertEqual(code, 0)
        self.assertNotIn("sure", out)

    def test_json_mode_never_asks_but_refuses_without_yes(self):
        code, out, _ = self.call("run", "--id", "cmd:shutdown", "--json")
        self.assertEqual(code, 1)
        self.assertIn("--yes", json.loads(out)["error"])
        self.assertEqual(self.runner.calls, [])

    def test_apps_never_ask(self):
        self.assertEqual(self.call("run", "obs")[0], 0)  # no answers given: it would fail if it asked


class Configuration(CliCase):
    def test_bad_configuration_is_exit_2_with_a_message(self):
        data = support.good_config()
        data["search"]["max_results"] = "many"
        self.config = str(self.write_config(data))
        code, _, err = self.call("list")
        self.assertEqual(code, 2)
        self.assertIn("search.max_results", err)

    def test_missing_configuration(self):
        self.config = str(self.tmp / "nope.json")
        self.assertEqual(self.call("list")[0], 2)

    def test_config_command_shows_path_and_content(self):
        code, out, _ = self.call("config", "--json")
        data = json.loads(out)
        self.assertEqual((code, data["path"]), (0, self.config))
        self.assertEqual(data["config"]["hotkey"]["key"], "d")


class Doctor(CliCase):
    def test_doctor_on_a_good_configuration(self):
        code, out, _ = self.call("doctor")
        self.assertEqual(code, 0)
        self.assertIn("4 application(s) found", out)
        self.assertIn("command+shift+d", out)

    def test_doctor_reports_a_bad_configuration_instead_of_crashing(self):
        self.config = str(self.tmp / "nope.json")
        code, out, _ = self.call("doctor")
        self.assertEqual(code, 1)
        self.assertIn("✘", out)
        self.assertIn("not found", out)

    def test_missing_app_folder_is_only_a_warning(self):
        data = support.good_config([self.tmp / "Applications", self.tmp / "nope"])
        self.config = str(self.write_config(data))
        code, out, _ = self.call("doctor")
        self.assertEqual(code, 0)
        self.assertIn("does not exist", out)


class RealProject(unittest.TestCase):
    def test_the_shipped_configuration_builds_items(self):
        from myconfig import load_config

        items = M.build_items(load_config(support.REAL_CONFIG))
        self.assertEqual(items[0].id, "cmd:shutdown")  # the command always comes first, apps (if any) after


if __name__ == "__main__":
    unittest.main()
