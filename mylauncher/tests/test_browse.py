"""Step 6 engine: "run" lists the apps, ";" lists the snippet groups, ";p" the snippets of the group,
icons/badges, the mode + highlight in the JSON, and the new configuration fields."""

import json
import unittest
from unittest import mock

import support
from test_cli import CliCase
from myconfig import ConfigError, parse_config
from myexpander import Snippet, describe_groups, group_of


def snippets_json(*pairs):
    return json.dumps({"matches": [{"trigger": t, "replace": r} for t, r in pairs]})


class BrowseCase(CliCase):
    def setUp(self):
        super().setUp()
        folder = self.tmp / "esp"
        folder.mkdir()
        (folder / "bookmark.yml").write_text(
            snippets_json((";pclarify", "Clarify this"), (";pexplain", "Explain this"), (";pexpand", "Expand this"), (";hcode", "```\n$|$\n```")),
            encoding="utf-8",
        )
        (folder / "emoji.yml").write_text(snippets_json((";ehappy", "😀"), (";esad", "😢")), encoding="utf-8")
        data = support.good_config(
            [self.tmp / "Applications"],
            expander={"folder": str(folder), "groups": {";p": {"name": "prompts", "icon": "🧠"}}},
        )
        self.config = str(self.write_config(data))
        patcher = mock.patch("myexpander.yaml_loader", return_value=json.loads)
        patcher.start()
        self.addCleanup(patcher.stop)

    def search(self, text):
        code, out, _ = self.call("search", text, "--json")
        return json.loads(out)


class RunMode(BrowseCase):
    def test_run_alone_lists_every_application(self):
        data = self.search("run")
        self.assertEqual(data["mode"], "run")
        self.assertEqual(data["highlight"], 3)
        self.assertEqual([r["title"] for r in data["results"]], ["Run Obsidian", "Run Safari", "Run Visual Studio Code", "Run Zen"])
        self.assertTrue(all(r["kind"] == "app" for r in data["results"]))

    def test_run_filters_by_what_follows(self):
        data = self.search("run saf")
        self.assertEqual([r["title"] for r in data["results"]], ["Run Safari"])

    def test_run_is_not_limited_by_max_results(self):
        folder = self.make_apps("Many", *[f"App{i:02d}" for i in range(30)])
        self.config = str(self.write_config(support.good_config([folder])))
        self.assertEqual(len(self.search("run")["results"]), 30)  # max_results is 8

    def test_part_of_the_word_is_still_the_normal_search(self):
        data = self.search("ru")
        self.assertEqual(data["mode"], "normal")
        self.assertEqual(data["results"][0]["id"], "prefix:run")


class SnippetBrowse(BrowseCase):
    def test_semicolon_lists_the_groups(self):
        data = self.search(";")
        self.assertEqual(data["mode"], "snippets")
        ids = [r["id"] for r in data["results"]]
        self.assertEqual(ids, ["group:;e", "group:;h", "group:;p"])
        by_id = {r["id"]: r for r in data["results"]}
        self.assertEqual(by_id["group:;p"]["title"], ";p  prompts")  # name from the configuration
        self.assertEqual(by_id["group:;p"]["icon"], "🧠")
        self.assertEqual(by_id["group:;p"]["subtitle"], "3 snippet(s)")
        self.assertEqual(by_id["group:;e"]["title"], ";e  emoji")  # name from the file name
        self.assertEqual(by_id["group:;p"]["complete"], ";p")
        self.assertEqual(by_id["group:;p"]["kind"], "prefix")

    def test_group_enter_writes_the_group_instead_of_running(self):
        # kind == "prefix": the window completes; the engine refuses to run it
        code, _, _ = self.call("run", "--id", "group:;p", "--yes", "--json")
        self.assertNotEqual(code, 0)

    def test_group_prefix_lists_its_snippets(self):
        data = self.search(";p")
        self.assertEqual([r["title"] for r in data["results"]], [";pclarify", ";pexpand", ";pexplain"])
        self.assertEqual(data["highlight"], 2)

    def test_longer_text_narrows_the_snippets(self):
        data = self.search(";pex")
        self.assertEqual([r["title"] for r in data["results"]], [";pexpand", ";pexplain"])

    def test_a_trigger_that_is_not_a_group_start_still_finds_text(self):
        data = self.search(";zzz")
        self.assertEqual(data["results"], [])

    def test_normal_text_never_shows_groups(self):
        data = self.search("clarify")
        self.assertEqual(data["mode"], "normal")
        self.assertTrue(all(not r["id"].startswith("group:") for r in data["results"]))

    def test_expander_off_means_semicolon_is_normal(self):
        data = support.good_config([self.tmp / "Applications"], expander={"enabled": False})
        self.config = str(self.write_config(data))
        self.assertEqual(self.search(";")["mode"], "normal")

    def test_group_length_three(self):
        data = support.good_config(
            [self.tmp / "Applications"], expander={"folder": str(self.tmp / "esp"), "group_length": 3}
        )
        self.config = str(self.write_config(data))
        ids = [r["id"] for r in self.search(";")["results"]]  # ";" + 2 letters now
        self.assertIn("group:;pc", ids)
        self.assertIn("group:;eh", ids)


class Modes(BrowseCase):
    def test_kill_mode_and_quicklink_mode_report_their_highlight(self):
        self.write_quicklinks([{"keyword": "yt", "url": "https://y.example/?q={query}"}])
        self.assertEqual((self.search("kill saf")["mode"], self.search("kill saf")["highlight"]), ("kill", 4))
        data = self.search("yt lofi")
        self.assertEqual((data["mode"], data["highlight"]), ("quicklink", 2))
        data = self.search("yt")  # no space yet: only a hint
        self.assertEqual(data["mode"], "normal")

    def test_normal_has_no_highlight(self):
        data = self.search("saf")
        self.assertEqual((data["mode"], data["highlight"]), ("normal", 0))


class IconsAndBadges(BrowseCase):
    def test_defaults_per_kind(self):
        rows = {r["id"]: r for r in self.search("run")["results"]}
        self.assertEqual(rows["app:Safari"]["icon"], "🚀")
        self.assertEqual(rows["app:Safari"]["badge"], "Application")
        self.assertTrue(rows["app:Safari"]["subtitle"].endswith("Applications"))

    def test_command_icon_and_description_from_configuration(self):
        cmd = {"id": "shutdown", "title": "Shutdown", "action": "shutdown", "icon": "🔌", "description": "Turn the Mac off", "confirm": True}
        self.config = str(self.write_config(support.good_config([self.tmp / "Applications"], commands=[cmd])))
        row = self.search("shut")["results"][0]
        self.assertEqual((row["icon"], row["subtitle"], row["badge"]), ("🔌", "Turn the Mac off", "Command"))

    def test_quicklink_icon(self):
        self.write_quicklinks([{"keyword": "yt", "url": "https://y.example/?q={query}", "icon": "📺"}])
        self.assertEqual(self.search("yt cats")["results"][0]["icon"], "📺")
        self.assertEqual(self.search("yt")["results"][0]["icon"], "📺")


class ConfigFields(unittest.TestCase):
    def parse(self, **changes):
        return parse_config(support.good_config(**changes), "t.json")

    def test_defaults(self):
        c = self.parse()
        self.assertEqual((c.run_word, c.max_browse_results, c.hotkey_swallow, c.window_style), ("run", 100, True, "borderless"))
        self.assertEqual(c.browser_command, ())
        self.assertEqual(c.window_colors["command"], "#ff9f0a")

    def test_colors_are_merged_and_validated(self):
        c = self.parse(window={"colors": {"command": "#00ff00"}})
        self.assertEqual((c.window_colors["command"], c.window_colors["background"]), ("#00ff00", "#1c1c1f"))
        with self.assertRaisesRegex(ConfigError, "window.colors.command"):
            self.parse(window={"colors": {"command": "green"}})
        with self.assertRaisesRegex(ConfigError, "window.colors.sky"):
            self.parse(window={"colors": {"sky": "#000000"}})

    def test_window_style(self):
        with self.assertRaisesRegex(ConfigError, "window.style"):
            self.parse(window={"style": "round"})

    def test_browser_command_needs_url(self):
        self.assertEqual(self.parse(browser={"command": ["zen", "-new-tab", "{url}"]}).browser_command, ("zen", "-new-tab", "{url}"))
        with self.assertRaisesRegex(ConfigError, r"\{url\}"):
            self.parse(browser={"command": ["zen"]})

    def test_words_must_differ_and_be_single(self):
        with self.assertRaisesRegex(ConfigError, "apps.word"):
            self.parse(apps={"folders": [], "exclude": [], "word": "run now"})
        with self.assertRaisesRegex(ConfigError, "different"):
            self.parse(apps={"folders": [], "exclude": [], "word": "kill"})

    def test_group_length_and_groups(self):
        with self.assertRaisesRegex(ConfigError, "group_length"):
            self.parse(expander={"group_length": 1})
        c = self.parse(expander={"groups": {";p": "prompts"}})
        self.assertEqual(c.expander_groups, {";p": ("prompts", "")})

    def test_browse_limit(self):
        with self.assertRaisesRegex(ConfigError, "max_browse_results"):
            self.parse(search={"max_results": 8, "ignore_accents": True, "fuzzy": True, "max_browse_results": 0})


class Groups(unittest.TestCase):
    def test_group_of(self):
        self.assertEqual(group_of(";pclarify", 2), ";p")

    def test_name_from_most_common_file(self):
        sn = [Snippet(";pa", "x", "", "/m/bookmark.yml"), Snippet(";pb", "x", "", "/m/bookmark.yml"), Snippet(";pc", "x", "", "/m/other.yml")]
        self.assertEqual(describe_groups(sn, 2, {}), {";p": ("bookmark", "", 3)})


if __name__ == "__main__":
    unittest.main()


class BrowserFromConfiguration(CliCase):
    def test_quicklink_opens_through_the_configured_browser_command(self):
        self.write_quicklinks([{"keyword": "yt", "url": "https://y.example/?q={query}"}])
        data = support.good_config([self.tmp / "Applications"], browser={"command": ["zen", "-new-tab", "{url}"]})
        self.config = str(self.write_config(data))
        code, _, _ = self.call("run", "--id", "link:yt", "--text=yt cats", "--yes")
        self.assertEqual(code, 0)
        self.assertEqual(self.runner.calls[-1], ["zen", "-new-tab", "https://y.example/?q=cats"])
