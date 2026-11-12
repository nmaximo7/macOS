"""myexpander.py (reading Espanso files), the copy_snippet action, and snippets in the search."""

import json
import unittest
from pathlib import Path

import support
from myactions import RunOptions, run_item
from myexpander import Snippet, find_yaml_files, load_snippets, parse_matches, preview, yaml_loader
from mytypes import Item
from test_cli import CliCase

HAS_YAML = yaml_loader() is not None
needs_yaml = unittest.skipUnless(HAS_YAML, "PyYAML is not installed")

MATCH_FILE = '''\
matches:
  - trigger: ";bsite"
    replace: "https://justtothepoint.com/"
  - trigger: ";hcode"
    replace: "```\\n$|$\\n```"
  - triggers: [";mail", ";email"]
    replace: me@example.com
    label: my address
  - trigger: ";multi"
    replace: |
      line one
      line two
'''


class Parsing(unittest.TestCase):
    """parse_matches works on plain Python data: no YAML needed."""

    def parse(self, matches, strip=True):
        return parse_matches({"matches": matches}, "f.yml", strip)

    def test_trigger_and_triggers(self):
        snippets, skipped = self.parse([{"trigger": ";a", "replace": "A"}, {"triggers": [";b", ";c"], "replace": "BC", "label": " two "}])
        self.assertEqual([(s.trigger, s.text, s.label) for s in snippets], [(";a", "A", ""), (";b", "BC", "two"), (";c", "BC", "two")])
        self.assertEqual(skipped, 0)
        self.assertEqual(snippets[0].source, "f.yml")

    def test_cursor_marker_is_removed_unless_asked(self):
        self.assertEqual(self.parse([{"trigger": ";h", "replace": "```\n$|$\n```"}])[0][0].text, "```\n\n```")
        self.assertEqual(self.parse([{"trigger": ";h", "replace": "a$|$b"}], strip=False)[0][0].text, "a$|$b")

    def test_things_that_need_espanso_are_skipped_and_counted(self):
        entries = [
            {"trigger": ";date", "replace": "{{today}}", "vars": [{"name": "today", "type": "date"}]},
            {"trigger": ";inline", "replace": "Hi {{name}}"},
            {"trigger": ";form", "form": "Name: [[n]]"},
            {"regex": ";r(\\d)", "replace": "x"},
            {"trigger": ";img", "image_path": "/a.png"},
            {"trigger": ";list", "replace": ["a"]},
            "not a dict",
            {"trigger": ";ok", "replace": "fine"},
        ]
        snippets, skipped = self.parse(entries)
        self.assertEqual([s.trigger for s in snippets], [";ok"])
        self.assertEqual(skipped, 7)

    def test_numbers_are_text_but_booleans_are_not(self):
        snippets, skipped = self.parse([{"trigger": ";n", "replace": 42}, {"trigger": ";b", "replace": True}])
        self.assertEqual([(s.trigger, s.text) for s in snippets], [(";n", "42")])
        self.assertEqual(skipped, 1)

    def test_blank_triggers_are_ignored(self):
        self.assertEqual(self.parse([{"trigger": "  ", "replace": "x"}, {"triggers": [3, ";ok"], "replace": "y"}])[0][0].trigger, ";ok")

    def test_files_that_are_not_snippet_files_are_not_errors(self):
        for data in (None, [], "text", {"toggle_key": "ALT"}, {"matches": "x"}, {"matches": None}):
            with self.subTest(data=data):
                self.assertEqual(parse_matches(data), ([], 0))

    def test_preview(self):
        self.assertEqual(preview("```\n\n```"), "``` ⏎ ```")
        self.assertEqual(preview("  one\n two  \n"), "one ⏎ two")
        self.assertEqual(preview("x" * 100, 10), "xxxxxxxxx…")
        self.assertEqual(preview(""), "")


class Reading(support.TempDirCase):
    def write(self, relative, text):
        path = self.tmp / "esp" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_finds_yml_and_yaml_in_all_subfolders_but_not_hidden_ones(self):
        self.write("espanso/match/base.yml", "matches: []")
        self.write("espanso/match/more/other.YAML", "matches: []")
        self.write("espanso/config/default.yml", "x: 1")
        self.write(".git/hooks/ignored.yml", "x: 1")
        self.write("espanso/match/.hidden.yml", "x: 1")
        self.write("espanso/match/notes.txt", "x")
        names = [p.name for p in find_yaml_files(self.tmp / "esp")]
        self.assertEqual(names, ["default.yml", "base.yml", "other.YAML"])

    def test_loading_with_a_fake_loader_needs_no_yaml(self):
        self.write("match/a.yml", json.dumps({"matches": [{"trigger": ";a", "replace": "A"}]}))
        self.write("match/b.yml", json.dumps({"matches": [{"trigger": ";a", "replace": "again"}, {"trigger": ";b", "replace": "B"}]}))
        scan = load_snippets(self.tmp / "esp", loader=json.loads)  # JSON is valid YAML, so json.loads stands in for it
        self.assertEqual([(s.trigger, s.text) for s in scan.snippets], [(";a", "A"), (";b", "B")])
        self.assertEqual((scan.files, scan.duplicates), (2, 1))  # the FIRST file (alphabetical) wins

    def test_a_broken_file_is_reported_and_the_others_still_load(self):
        self.write("match/a.yml", "this is {not json")
        self.write("match/b.yml", json.dumps({"matches": [{"trigger": ";b", "replace": "B"}]}))
        scan = load_snippets(self.tmp / "esp", loader=json.loads)
        self.assertEqual([s.trigger for s in scan.snippets], [";b"])
        self.assertEqual(len(scan.problems), 1)
        self.assertTrue(scan.problems[0].startswith("a.yml:"))

    def test_missing_folder(self):
        scan = load_snippets(self.tmp / "nope")
        self.assertEqual(scan.snippets, [])
        self.assertIn("folder not found", scan.problems[0])

    def test_missing_pyyaml_is_flagged_not_raised(self):
        self.write("match/a.yml", "matches: []")
        from unittest import mock

        with mock.patch("myexpander.yaml_loader", return_value=None):
            self.assertTrue(load_snippets(self.tmp / "esp").missing_yaml)

    def test_unreadable_encoding_is_a_problem_not_a_crash(self):
        path = self.write("match/a.yml", "")
        path.write_bytes(b"\xff\xfe\x00bad")
        scan = load_snippets(self.tmp / "esp", loader=json.loads)
        self.assertEqual(len(scan.problems), 1)

    @needs_yaml
    def test_real_espanso_file(self):
        self.write("espanso/match/base.yml", MATCH_FILE)
        self.write("espanso/config/default.yml", "toggle_key: ALT\nbackend: Clipboard\n")
        scan = load_snippets(self.tmp / "esp")
        by = {s.trigger: s for s in scan.snippets}
        self.assertEqual(sorted(by), [";bsite", ";email", ";hcode", ";mail", ";multi"])
        self.assertEqual(by[";bsite"].text, "https://justtothepoint.com/")
        self.assertEqual(by[";hcode"].text, "```\n\n```")  # the cursor marker is gone
        self.assertEqual(by[";mail"].label, "my address")
        self.assertEqual(by[";multi"].text, "line one\nline two\n")
        self.assertEqual((scan.files, scan.problems, scan.skipped), (2, [], 0))

    @needs_yaml
    def test_invalid_real_yaml_is_a_problem(self):
        self.write("match/bad.yml", "matches:\n  - trigger: ';a'\n   replace: oops\n")
        scan = load_snippets(self.tmp / "esp")
        self.assertEqual(len(scan.problems), 1)


class CopyAction(unittest.TestCase):
    ITEM = Item("snip:;bsite", ";bsite", "snippet", "copy_snippet", target="https://justtothepoint.com/", subtitle="https://justtothepoint.com/")

    def test_copies_then_notifies(self):
        runner = support.FakeRunner()
        result = run_item(self.ITEM, runner=runner)
        self.assertTrue(result.ok)
        self.assertEqual(runner.calls[0], ["pbcopy"])
        self.assertEqual(runner.inputs, ["https://justtothepoint.com/"])  # exactly the text, sent to pbcopy
        self.assertEqual(runner.calls[1][0], "osascript")
        script = runner.calls[1][2]
        self.assertIn('display notification "https://justtothepoint.com/"', script)
        self.assertIn(';bsite copied to the clipboard', script)
        self.assertIn("copied to the clipboard (27 characters)", result.message)

    def test_notification_can_be_switched_off(self):
        runner = support.FakeRunner()
        run_item(self.ITEM, runner=runner, options=RunOptions(notify=False))
        self.assertEqual([c[0] for c in runner.calls], ["pbcopy"])

    def test_quotes_and_backslashes_cannot_break_the_notification(self):
        item = Item("snip:;q", ";q", "snippet", "copy_snippet", target='say "hi" \\ done', subtitle='say "hi" \\ done')
        runner = support.FakeRunner()
        run_item(item, runner=runner)
        self.assertIn('say \\"hi\\" \\\\ done', runner.calls[1][2])

    def test_text_is_copied_exactly_even_when_long_or_multiline_or_unicode(self):
        text = "línea 1\n\tlínea 2 ñ 😀\n" + "x" * 5000
        item = Item("snip:;l", ";l", "snippet", "copy_snippet", target=text, subtitle="preview")
        runner = support.FakeRunner()
        run_item(item, runner=runner)
        self.assertEqual(runner.inputs, [text])
        self.assertLessEqual(len(runner.calls[1][2]), 300)  # the notification is cut short, the clipboard is not

    def test_a_failed_notification_does_not_fail_the_copy(self):
        class Flaky(support.FakeRunner):
            def __call__(self, command, input_text=None):
                if command[0] == "osascript":
                    raise FileNotFoundError()
                return super().__call__(command, input_text)

        self.assertTrue(run_item(self.ITEM, runner=Flaky()).ok)

    def test_failed_copy(self):
        result = run_item(self.ITEM, runner=support.FakeRunner(returncode=1, stderr="boom"))
        self.assertFalse(result.ok)
        self.assertIn("boom", result.message)
        result = run_item(self.ITEM, runner=support.FakeRunner(error=FileNotFoundError()))
        self.assertIn("pbcopy", result.message)

    def test_dry_run_copies_nothing(self):
        runner = support.FakeRunner()
        result = run_item(self.ITEM, runner=runner, dry_run=True)
        self.assertTrue(result.ok)
        self.assertEqual((runner.calls, runner.inputs), ([], []))
        self.assertIn("Would copy 27 characters", result.message)


@needs_yaml
class InTheLauncher(CliCase):
    def setUp(self):
        super().setUp()
        folder = self.tmp / "Espanso" / "Library" / "Application Support"
        (folder / "espanso" / "match").mkdir(parents=True)
        (folder / "espanso" / "match" / "base.yml").write_text(MATCH_FILE, encoding="utf-8")
        (folder / "espanso" / "match" / "dyn.yml").write_text('matches:\n  - trigger: ";date"\n    replace: "{{d}}"\n    vars: []\n', encoding="utf-8")
        self.folder = folder
        data = support.good_config([self.tmp / "Applications"], expander={"folder": str(folder)})
        self.config = str(self.write_config(data))

    def search(self, *words):
        code, out, _ = self.call("search", *words, "--json")
        return code, json.loads(out)

    def test_typing_a_trigger_finds_it(self):
        code, data = self.search(";bsite")
        top = data["results"][0]
        self.assertEqual((code, top["id"], top["kind"], top["title"]), (0, "snip:;bsite", "snippet", ";bsite"))
        self.assertEqual(top["subtitle"], "https://justtothepoint.com/")
        self.assertEqual(top["score"], 100)
        self.assertEqual(data["completion"], ";bsite")

    def test_partial_trigger_and_label(self):
        self.assertEqual(self.search(";bs")[1]["results"][0]["id"], "snip:;bsite")
        # the label is searched too: both triggers of that entry share it (equal score, so alphabetical)
        self.assertEqual([r["id"] for r in self.search("address")[1]["results"]], ["snip:;email", "snip:;mail"])

    def test_the_subtitle_text_is_not_searched(self):
        self.assertEqual(self.search("justtothepoint")[1]["results"], [])

    def test_snippets_stay_out_of_the_empty_list(self):
        _, data = self.search()
        self.assertFalse([r for r in data["results"] if r["kind"] == "snippet"])

    def test_dynamic_snippets_are_not_offered(self):
        self.assertEqual(self.search(";date")[1]["results"], [])

    def test_run_copies_to_the_clipboard_and_notifies(self):
        system = support.FakeSystem()
        code, out, _ = self.call("run", ";bsite", runner=system)
        self.assertEqual(code, 0)
        self.assertEqual(system.clipboard, "https://justtothepoint.com/")
        self.assertIn(["pbcopy"], system.calls)
        self.assertTrue(any(c[0] == "osascript" for c in system.calls))
        self.assertIn(";bsite copied", out)

    def test_run_by_id(self):
        system = support.FakeSystem()
        self.assertEqual(self.call("run", "--id", "snip:;hcode", runner=system)[0], 0)  # even without --text
        self.assertEqual(system.clipboard, "```\n\n```")

    def test_notification_setting(self):
        data = support.good_config([self.tmp / "Applications"], expander={"folder": str(self.folder), "notification": False})
        self.config = str(self.write_config(data))
        system = support.FakeSystem()
        self.call("run", ";bsite", runner=system)
        self.assertFalse(any(c[0] == "osascript" for c in system.calls))

    def test_cursor_marker_setting(self):
        data = support.good_config([self.tmp / "Applications"], expander={"folder": str(self.folder), "strip_cursor_marker": False})
        self.config = str(self.write_config(data))
        system = support.FakeSystem()
        self.call("run", ";hcode", runner=system)
        self.assertEqual(system.clipboard, "```\n$|$\n```")

    def test_snippets_count_for_most_used_first(self):
        usage = self.tmp / "u.json"
        data = support.good_config([self.tmp / "Applications"], expander={"folder": str(self.folder)}, usage={"enabled": True, "file": str(usage)})
        self.config = str(self.write_config(data))
        self.call("run", ";mail", runner=support.FakeSystem())
        self.assertEqual(json.loads(usage.read_text())["counts"], {"snip:;mail": 1})

    def test_list_includes_snippets(self):
        _, out, _ = self.call("list", "--json")
        ids = [i["id"] for i in json.loads(out)]
        self.assertIn("snip:;bsite", ids)
        self.assertIn("snip:;email", ids)

    def test_doctor_reports_the_snippets(self):
        _, out, _ = self.call("doctor")
        self.assertIn("snippets: 5 trigger(s) from 2 file(s)", out)
        self.assertIn("1 entry skipped", out)

    def test_not_configured(self):
        self.config = str(self.write_config(support.good_config([self.tmp / "Applications"])))
        self.assertIn("snippets: not configured", self.call("doctor")[1])
        self.assertEqual(self.search(";bsite")[1]["results"], [])

    def test_missing_folder_is_a_warning_and_search_still_works(self):
        data = support.good_config([self.tmp / "Applications"], expander={"folder": str(self.tmp / "nope")})
        self.config = str(self.write_config(data))
        code, out, _ = self.call("doctor")
        self.assertEqual(code, 0)
        self.assertIn("does not exist", out)
        self.assertEqual(self.search("obs")[0], 0)


class WithoutYaml(CliCase):
    def test_missing_pyyaml_only_switches_snippets_off(self):
        from unittest import mock

        (self.tmp / "esp").mkdir()
        data = support.good_config([self.tmp / "Applications"], expander={"folder": str(self.tmp / "esp")})
        self.config = str(self.write_config(data))
        with mock.patch("myexpander.yaml_loader", return_value=None):
            self.assertEqual(self.call("search", "obs", "--json")[0], 0)
            _, out, _ = self.call("doctor")
        self.assertIn("PyYAML is not installed", out)


if __name__ == "__main__":
    unittest.main()
