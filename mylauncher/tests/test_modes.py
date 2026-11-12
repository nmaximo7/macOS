"""mylauncher.py: quicklinks ("yt lofi"), kill ("kill ghostty") and "most used first", end to end."""

import json
import unittest

import support
from test_cli import CliCase

OBSIDIAN, GHOSTTY = "/Applications/Obsidian.app", "/Applications/Ghostty.app"
LINKS = [
    {"keyword": "yt", "url": "https://www.youtube.com/results?search_query={query}"},
    {"keyword": "jttp", "url": "https://justtothepoint.com/search/?query=", "title": "JustToThePoint"},
]


class Quicklinks(CliCase):
    def setUp(self):
        super().setUp()
        self.write_quicklinks(LINKS)

    def search(self, *words):
        code, out, _ = self.call("search", *words, "--json")
        return code, json.loads(out)

    def test_keyword_space_query_gives_one_ready_search(self):
        code, data = self.search("yt", "lofi beats")
        self.assertEqual(code, 0)
        self.assertEqual(len(data["results"]), 1)
        result = data["results"][0]
        self.assertEqual(result["id"], "link:yt")
        self.assertEqual(result["kind"], "quicklink")
        self.assertEqual(result["title"], "Search youtube.com for lofi beats")
        self.assertEqual(result["target"], "https://www.youtube.com/results?search_query=lofi+beats")
        self.assertEqual(data["completion"], "yt lofi beats")

    def test_keyword_without_space_is_a_hint_that_completes_with_a_space(self):
        _, data = self.search("yt")
        top = data["results"][0]
        self.assertEqual((top["id"], top["kind"]), ("link:yt", "prefix"))
        self.assertEqual(data["completion"], "yt ")  # Tab writes "yt " and you go on typing

    def test_partial_keyword_also_completes(self):
        _, data = self.search("jt")
        self.assertEqual(data["results"][0]["id"], "link:jttp")
        self.assertEqual(data["completion"], "jttp ")

    def test_keyword_and_a_space_but_no_query_yet(self):
        _, data = self.search("yt ")
        self.assertEqual(data["results"][0]["title"], "Search youtube.com: type what to look for")
        self.assertEqual(data["completion"], "yt ")
        self.assertEqual(data["results"][0]["target"], "https://www.youtube.com/results?search_query=")

    def test_keyword_is_case_insensitive_and_extra_spaces_are_ignored(self):
        _, data = self.search("YT   lofi")
        self.assertEqual(data["results"][0]["target"], "https://www.youtube.com/results?search_query=lofi")

    def test_url_without_placeholder(self):
        _, data = self.search("jttp", "hello world")
        self.assertEqual(data["results"][0]["target"], "https://justtothepoint.com/search/?query=hello+world")
        self.assertIn("JustToThePoint", data["results"][0]["title"])

    def test_special_characters_are_encoded(self):
        _, data = self.search("yt", "c++ & more")
        self.assertTrue(data["results"][0]["target"].endswith("search_query=c%2B%2B+%26+more"))

    def test_unknown_first_word_is_a_normal_search(self):
        code, data = self.search("zzz", "lofi")
        self.assertEqual((code, data["results"]), (1, []))

    def test_enter_opens_the_url_in_the_browser(self):
        code, out, _ = self.call("run", "yt", "lofi beats")
        self.assertEqual(code, 0)
        self.assertEqual(self.runner.calls, [["open", "https://www.youtube.com/results?search_query=lofi+beats"]])

    def test_run_by_id_needs_the_text(self):
        code, _, _ = self.call("run", "--id", "link:yt", "--text", "yt lofi beats")
        self.assertEqual(code, 0)
        self.assertTrue(self.runner.calls[0][1].endswith("search_query=lofi+beats"))

    def test_text_starting_with_a_dash_is_safe(self):
        code, _, _ = self.call("run", "--id", "link:yt", "--text=yt -rf")
        self.assertEqual(code, 0)
        self.assertTrue(self.runner.calls[0][1].endswith("search_query=-rf"))

    def test_enter_on_the_hint_does_not_open_anything(self):
        code, out, _ = self.call("run", "yt")
        self.assertEqual(code, 1)
        self.assertIn("type something after it", out)
        self.assertEqual(self.runner.calls, [])

    def test_dry_run(self):
        code, out, _ = self.call("run", "yt", "x", "--dry-run")
        self.assertEqual((code, self.runner.calls), (0, []))
        self.assertIn("search_query=x", out)

    def test_hints_are_listed(self):
        _, out, _ = self.call("list", "--json")
        ids = [i["id"] for i in json.loads(out)]
        self.assertIn("link:yt", ids)
        self.assertIn("link:jttp", ids)
        self.assertIn("prefix:kill", ids)


class Kill(CliCase):
    def setUp(self):
        super().setUp()
        self.system = support.FakeSystem({OBSIDIAN: [812], GHOSTTY: [20, 21], "/Applications/Python.app": [5]})
        self.system.add_noise()

    def call_kill(self, *args, **kw):
        return self.call(*args, runner=self.system, **kw)

    def titles(self, *words):
        _, out, _ = self.call_kill("search", *words, "--json")
        return [r["title"] for r in json.loads(out)["results"]]

    def test_kill_alone_lists_the_running_apps(self):
        self.assertEqual(self.titles("kill"), ["Kill Ghostty", "Kill Obsidian"])  # no Python (protected), no helpers, no Dock

    def test_kill_with_a_filter(self):
        self.assertEqual(self.titles("kill", "gh"), ["Kill Ghostty"])
        self.assertEqual(self.titles("KILL", "OBS"), ["Kill Obsidian"])
        self.assertEqual(self.titles("kill", "zzz"), [])

    def test_the_word_kill_in_the_titles_does_not_match_the_filter(self):
        self.assertEqual(self.titles("kill", "kil"), [])

    def test_completion_and_kind(self):
        _, out, _ = self.call_kill("search", "kill", "gh", "--json")
        data = json.loads(out)
        self.assertEqual(data["completion"], "kill ghostty")
        self.assertEqual(data["results"][0]["kind"], "kill")

    def test_apps_that_are_not_running_are_not_listed(self):
        self.assertNotIn("Kill Safari", self.titles("kill"))  # installed (fake folder), but not running

    def test_the_hint_completes_the_word(self):
        _, out, _ = self.call("search", "kil", "--json")
        data = json.loads(out)
        self.assertEqual(data["completion"], "kill ")
        self.assertEqual(data["results"][0]["kind"], "prefix")

    def test_run_the_best_match(self):
        code, out, _ = self.call_kill("run", "kill", "gh")
        self.assertEqual(code, 0)
        self.assertIn("Ghostty quit", out)
        self.assertEqual(self.system.procs.keys() & {20, 21}, set())

    def test_run_by_id_with_the_text(self):
        code, _, _ = self.call_kill("run", "--id", "kill:Obsidian", "--text", "kill obs", "--json")
        self.assertEqual(code, 0)
        self.assertNotIn(812, self.system.procs)

    def test_a_frozen_app_answers_needs_force_and_force_kills_it(self):
        self.system.quits = self.system.term_works = False
        code, out, _ = self.call_kill("run", "--id", "kill:Obsidian", "--text", "kill obs", "--json")
        answer = json.loads(out)["result"]
        self.assertEqual((code, answer["ok"], answer["needs_force"]), (1, False, True))
        self.assertIn(812, self.system.procs)
        code, out, _ = self.call_kill("run", "--id", "kill:Obsidian", "--text", "kill obs", "--force", "--json")
        self.assertEqual(code, 0)
        self.assertNotIn(812, self.system.procs)

    def test_auto_force_setting(self):
        data = support.good_config([self.tmp / "Applications"], kill={"auto_force": True, "grace_seconds": 1})
        self.config = str(self.write_config(data))
        self.system.quits = self.system.term_works = False
        code, out, _ = self.call_kill("run", "kill", "obs")
        self.assertEqual(code, 0)
        self.assertIn("force quit", out)

    def test_another_kill_word(self):
        data = support.good_config([self.tmp / "Applications"], kill={"word": "quit"})
        self.config = str(self.write_config(data))
        self.assertEqual(self.titles("quit", "gh"), ["Kill Ghostty"])

    def test_dry_run_does_not_touch_anything(self):
        code, out, _ = self.call_kill("run", "kill", "gh", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("Would run", out)
        self.assertEqual({c[0] for c in self.system.calls}, {"ps"})  # only looked at the process list

    def test_id_of_an_app_that_is_not_running(self):
        code, _, err = self.call_kill("run", "--id", "kill:Nothing", "--text", "kill n")
        self.assertEqual(code, 1)
        self.assertIn("no item", err)


class MostUsedFirst(CliCase):
    def setUp(self):
        super().setUp()
        usage = self.tmp / "state" / "usage.json"
        data = support.good_config([self.make_apps("Applications", "Safari", "Slack", "Spotify")], usage={"enabled": True, "file": str(usage)})
        self.config = str(self.write_config(data))
        self.usage = usage

    def titles(self, *words):
        _, out, _ = self.call("search", *words, "--json")
        return [r["title"] for r in json.loads(out)["results"]]

    def test_without_history_it_is_alphabetical(self):
        self.assertEqual([t for t in self.titles("s") if t.startswith("Run S")], ["Run Safari", "Run Slack", "Run Spotify"])

    def test_the_most_used_app_comes_first(self):
        for _ in range(3):
            self.call("run", "--id", "app:Slack")
        self.assertEqual([t for t in self.titles("s") if t.startswith("Run S")][0], "Run Slack")

    def test_with_nothing_typed_favourites_lead_the_list(self):
        self.call("run", "--id", "app:Spotify")
        self.call("run", "--id", "app:Spotify")
        self.call("run", "--id", "app:Slack")
        self.assertEqual(self.titles()[:2], ["Run Spotify", "Run Slack"])

    def test_the_bonus_is_capped(self):
        for _ in range(30):
            self.call("run", "--id", "app:Slack")
        _, out, _ = self.call("search", "slack", "--json")
        self.assertEqual(json.loads(out)["results"][0]["score"], 60 + 10)  # a word starts with it (60) + the max bonus (10)

    def test_only_real_successful_runs_are_counted(self):
        self.call("run", "--id", "app:Slack", "--dry-run")  # dry run
        self.call("run", "--id", "app:Slack", runner=support.FakeRunner(returncode=1, stderr="boom"))  # failed
        self.call("run", "--id", "prefix:kill")  # a hint
        self.assertFalse(self.usage.exists())
        self.call("run", "--id", "app:Slack")
        self.assertEqual(json.loads(self.usage.read_text())["counts"], {"app:Slack": 1})

    def test_quicklinks_and_kill_are_counted_by_item_not_by_text(self):
        self.write_quicklinks(LINKS)
        self.call("run", "yt", "one")
        self.call("run", "yt", "two")
        self.assertEqual(json.loads(self.usage.read_text())["counts"], {"link:yt": 2})

    def test_history_command(self):
        self.call("run", "--id", "app:Slack")
        self.call("run", "--id", "app:Slack")
        self.call("run", "--id", "app:Safari")
        code, out, _ = self.call("history")
        self.assertEqual(code, 0)
        self.assertEqual([line.split(None, 1) for line in out.strip().splitlines()], [["2", "Run Slack"], ["1", "Run Safari"]])
        _, out, _ = self.call("history", "--json")
        self.assertEqual(json.loads(out)[0], {"id": "app:Slack", "count": 2, "title": "Run Slack"})

    def test_history_clear(self):
        self.call("run", "--id", "app:Slack")
        code, out, _ = self.call("history", "--clear")
        self.assertEqual(code, 0)
        self.assertFalse(self.usage.exists())
        self.assertIn("nothing yet", self.call("history")[1])

    def test_switched_off(self):
        data = support.good_config([self.tmp / "Applications"], usage={"enabled": False, "file": str(self.usage)})
        self.config = str(self.write_config(data))
        self.call("run", "--id", "app:Slack")
        self.assertFalse(self.usage.exists())
        self.assertIn("switched off", self.call("history")[1])

    def test_a_damaged_history_file_does_not_stop_the_launcher(self):
        self.usage.parent.mkdir(parents=True)
        self.usage.write_text("garbage")
        self.assertEqual(self.call("search", "slack")[0], 0)


class DoctorNew(CliCase):
    def test_doctor_reports_quicklinks_usage_and_kill(self):
        self.write_quicklinks(LINKS)
        code, out, _ = self.call("doctor")
        self.assertIn("quicklinks: 2", out)
        self.assertIn("usage history is switched off", out)
        self.assertIn("'kill <name>' waits 5 s, then asks before force quit", out)

    def test_missing_quicklinks_file_is_a_warning_only(self):
        code, out, _ = self.call("doctor")
        self.assertEqual(code, 0)
        self.assertIn("file not found: no quicklinks", out)


if __name__ == "__main__":
    unittest.main()
