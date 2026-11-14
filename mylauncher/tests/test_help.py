"""Step 7: the `help` command (cli/myhelp.py): topics, rows, search, cache, CLI, report."""

import json
import unittest
from pathlib import Path
from unittest import mock

import support
from test_cli import CliCase
from myconfig import ConfigError, parse_config
import myhelp

ALIASES = "ll='ls -la'\ngs=git\\ status\nname='it'\\''s'\n"
ZSH_FUNCTIONS = """# Build the site and open it.
# Needs hugo.
build_site() {
  if [ -d public ]; then
    rm -rf public
  fi
  hugo
}

_private_helper() {
  echo hidden
}

function deploy {
  rsync -av public/ server:/www/
}
"""
AEROSPACE = """
[mode.main.binding]
alt-h = 'focus left'
alt-shift-1 = ['move-node-to-workspace T', 'workspace T']

[[on-window-detected]]
if.app-id = 'org.python.python'
run = 'layout floating'
"""
HELP_SH = """#!/bin/bash
sec_raycast() {
  echo "Raycast"
  echo "  cmd+space   open"
}
sec_keyboard() {
  printf '\\033[1mKeyboard\\033[0m'
}
other_function() {
  echo nope
}
"""


class HelpCase(CliCase):
    """A fake home: every file `help` reads is inside self.tmp."""

    def setUp(self):
        super().setUp()
        t = self.tmp
        (t / ".zsh_aliases").write_text("# list files, long\nalias ll='ls -la'\nalias gs='git status'\n", encoding="utf-8")
        (t / ".zsh_functions").write_text(ZSH_FUNCTIONS, encoding="utf-8")
        (t / "aerospace.toml").write_text(AEROSPACE, encoding="utf-8")
        (t / "skills" / "docs").mkdir(parents=True)
        (t / "skills" / "docs" / "SKILL.md").write_text("---\nname: docs\ndescription: Make documents\n---\nBody", encoding="utf-8")
        (t / "scripts").mkdir()
        (t / "scripts" / "backup.sh").write_text("#!/bin/bash\n# Back up the disk\nset -e\nrsync a b\n", encoding="utf-8")
        (t / "scripts" / "tool.py").write_text('#!/usr/bin/env python3\n"""Convert things."""\nprint(1)\n', encoding="utf-8")
        (t / "scripts" / "help.sh").write_text(HELP_SH, encoding="utf-8")
        self.set_help()
        self.runner = support.FakeRunner(outputs={("zsh", "-ic", "alias"): ALIASES})

    def set_help(self, **extra):
        t = self.tmp
        section = {
            "cache_seconds": 0,
            "aliases_file": str(t / ".zsh_aliases"),
            "functions_file": str(t / ".zsh_functions"),
            "aerospace_config": str(t / "aerospace.toml"),
            "skills_folder": str(t / "skills"),
            "help_script": str(t / "scripts" / "help.sh"),
            "scripts_folder": str(t / "scripts"),
            "cache_file": str(t / "cache.json"),
        }
        section.update(extra)
        data = support.good_config([self.tmp / "Applications"], help=section, expander={"folder": str(t / "esp")})
        self.config = str(self.write_config(data))

    def search(self, text):
        code, out, _ = self.call("search", text, "--json")
        return json.loads(out)

    def titles(self, text):
        return [r["title"] for r in self.search(text)["results"]]


class Topics(HelpCase):
    def test_help_alone_lists_the_topics(self):
        data = self.search("help")
        self.assertEqual((data["mode"], data["highlight"]), ("help", 4))
        self.assertEqual([r["title"] for r in data["results"]], list(myhelp.TOPICS))
        self.assertEqual(data["results"][0]["complete"], "help aliases ")

    def test_part_of_a_topic_filters_the_topics(self):
        self.assertEqual(self.titles("help al")[0], "aliases")
        self.assertEqual(self.titles("help fu"), ["functions"])

    def test_synonyms(self):
        for word, topic in (("zsh_alias", "aliases"), ("zsh_functions", "functions"), ("sys", "system"), ("snippets", "espanso")):
            self.assertEqual(myhelp.resolve_topic(word), topic)
        self.assertEqual(myhelp.resolve_topic("nonsense"), "")

    def test_the_topic_is_painted_too(self):
        self.assertEqual(self.search("help zsh_alias")["highlight"], len("help zsh_alias"))
        self.assertEqual(self.search("help al")["highlight"], 4)

    def test_the_word_help_without_a_space_is_only_a_hint_until_complete(self):
        self.assertEqual(self.search("hel")["mode"], "normal")
        self.assertEqual(self.search("hel")["results"][0]["id"], "prefix:help")


class Aliases(HelpCase):
    def test_parse(self):
        self.assertEqual(myhelp.parse_alias_output(ALIASES), {"ll": "ls -la", "gs": "git\\ status", "name": "it's"})

    def test_rows_have_value_comment_and_detail(self):
        rows = {r["title"]: r for r in self.search("help aliases")["results"]}
        self.assertEqual(sorted(rows), ["gs", "ll", "name"])
        self.assertEqual(rows["ll"]["subtitle"], "ls -la   # list files, long")
        self.assertEqual((rows["ll"]["kind"], rows["ll"]["icon"], rows["ll"]["badge"]), ("help", "🔗", "Alias"))
        self.assertIn("alias ll='ls -la'", rows["ll"]["detail"])
        self.assertIn("list files, long", rows["ll"]["detail"])

    def test_filter(self):
        self.assertEqual(self.titles("help aliases git"), ["gs"])
        self.assertEqual(self.titles("help zsh_alias ll"), ["ll"])

    def test_zsh_missing(self):
        self.runner = support.FakeRunner(error=FileNotFoundError())
        row = self.search("help aliases")["results"][0]
        self.assertEqual(row["id"], "info:help:aliases")
        self.assertIn("zsh was not found", row["subtitle"])


class Functions(unittest.TestCase):
    def test_blocks(self):
        blocks = myhelp.function_blocks(ZSH_FUNCTIONS)
        self.assertEqual([b[0] for b in blocks], ["build_site", "deploy"])  # _private_helper is left out
        name, comment, source = blocks[0]
        self.assertEqual(comment, "Build the site and open it.\nNeeds hugo.")
        self.assertTrue(source.startswith("build_site() {") and source.endswith("}"))
        self.assertIn("rm -rf public", source)  # the inner } of the `if` did not end the function
        self.assertNotIn("_private", source)

    def test_function_keyword_without_parentheses(self):
        self.assertEqual(myhelp.function_blocks("function deploy {\n  x\n}\n")[0][0], "deploy")


class FunctionRows(HelpCase):
    def test_rows(self):
        data = self.search("help functions")
        rows = {r["title"]: r for r in data["results"]}
        self.assertEqual(sorted(rows), ["build_site", "deploy"])
        self.assertEqual(rows["build_site"]["subtitle"], "Build the site and open it.")
        self.assertIn("hugo", rows["build_site"]["detail"])
        self.assertEqual(rows["deploy"]["subtitle"], "rsync -av public/ server:/www/")  # no comment: the first line of the body

    def test_search_in_the_comment(self):
        self.assertEqual(self.titles("help functions hugo"), ["build_site"])

    def test_missing_file_is_explained(self):
        self.set_help(functions_file=str(self.tmp / "nope"))
        row = self.search("help functions")["results"][0]
        self.assertIn("file not found", row["subtitle"])


class Others(HelpCase):
    def test_aerospace(self):
        rows = {r["title"]: r for r in self.search("help aerospace")["results"]}
        self.assertEqual(rows["alt-h"]["subtitle"], "focus left")
        self.assertEqual(rows["alt-shift-1"]["subtitle"], "move-node-to-workspace T ; workspace T")
        rule = next(r for r in rows.values() if r["title"].startswith("rule:"))
        self.assertIn("org.python.python", rule["title"])
        self.assertEqual(rule["subtitle"], "layout floating")

    def test_aerospace_bad_toml_and_missing(self):
        (self.tmp / "aerospace.toml").write_text("[[[", encoding="utf-8")
        self.assertIn("cannot read", self.search("help aero")["results"][0]["subtitle"])
        self.set_help(aerospace_config=str(self.tmp / "nope.toml"))
        self.assertIn("file not found", self.search("help aero")["results"][0]["subtitle"])

    def test_espanso(self):
        esp = self.tmp / "esp"
        esp.mkdir()
        (esp / "base.yml").write_text(json.dumps({"matches": [{"trigger": ";bsite", "replace": "https://x.test/\nsecond"}]}), encoding="utf-8")
        with mock.patch("myexpander.yaml_loader", return_value=json.loads):
            row = self.search("help espanso")["results"][0]
        self.assertEqual((row["title"], row["subtitle"]), (";bsite", "https://x.test/"))
        self.assertIn("base.yml", row["detail"])
        self.assertEqual(row["id"], "help:espanso:;bsite")

    def test_skills_without_pyyaml(self):
        with mock.patch("myexpander.yaml_loader", return_value=None):
            row = self.search("help skills")["results"][0]
        self.assertEqual((row["title"], row["subtitle"]), ("docs", "Make documents"))

    def test_keys_sections_are_cleaned(self):
        rows = {r["title"]: r for r in self.search("help keys")["results"]}
        self.assertEqual(sorted(rows), ["keyboard", "raycast"])  # other_function is not a sec_
        self.assertEqual(rows["raycast"]["detail"], "Raycast\n  cmd+space   open")
        self.assertEqual(rows["keyboard"]["detail"], "Keyboard")  # printf and colour codes removed

    def test_scripts(self):
        rows = {r["title"]: r for r in self.search("help scripts")["results"]}
        self.assertEqual(rows["backup.sh"]["subtitle"], "Back up the disk")
        self.assertEqual(rows["tool.py"]["subtitle"], "Convert things.")
        self.assertIn("rsync a b", rows["backup.sh"]["detail"])

    def test_system(self):
        self.runner = support.FakeRunner(outputs={("sw_vers", "-productVersion"): "15.1\n", ("sysctl", "-n", "hw.memsize"): str(16 * 1024**3)})
        rows = {r["title"]: r["subtitle"] for r in self.search("help system")["results"]}
        self.assertEqual((rows["macOS"], rows["Memory"]), ("15.1", "16.0 GB"))
        self.assertEqual(rows["zsh"], "unknown")  # a command that printed nothing

    def test_launcher_lists_the_words_of_the_configuration(self):
        titles = self.titles("help launcher")
        for word in ("run", "kill", "help", "hotkey", ";"):
            self.assertIn(word, titles)

    def test_script_summary_skips_shebang_and_set(self):
        self.assertEqual(myhelp.script_summary("#!/bin/sh\nset -e\n# real\n"), "real")  # set -e is code, not the summary
        self.assertEqual(myhelp.script_summary("#!/bin/sh\necho hi\n# later\n"), "")  # code first: no summary


class RunningARow(HelpCase):
    def test_enter_copies_the_name_of_an_alias_with_a_notification(self):
        code, out, _ = self.call("run", "--id", "help:aliases:ll", "--text=help aliases ll", "--yes", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(self.runner.inputs, ["ll"])
        self.assertTrue(any(c[0] == "osascript" for c in self.runner.calls))

    def test_enter_copies_the_whole_text_of_a_cheat_sheet(self):
        self.call("run", "--id", "help:keys:raycast", "--text=help keys", "--yes", "--json")
        self.assertEqual(self.runner.inputs, ["Raycast\n  cmd+space   open"])

    def test_help_rows_are_not_remembered_as_favourites(self):
        usage = self.tmp / "usage.json"
        data = support.good_config([self.tmp / "Applications"], usage={"enabled": True, "file": str(usage)}, help={"cache_seconds": 0, "aliases_file": str(self.tmp / ".zsh_aliases")})
        self.config = str(self.write_config(data))
        self.call("run", "--id", "help:aliases:ll", "--text=help aliases ll", "--yes")
        self.assertFalse(usage.exists())


class Cache(HelpCase):
    def test_slow_topics_are_remembered_and_refresh_skips_the_memory(self):
        self.set_help(cache_seconds=600)
        self.search("help aliases")
        first = len(self.runner.calls)
        self.search("help aliases ll")
        self.assertEqual(len(self.runner.calls), first)  # answered from the cache file
        self.runner.outputs[("zsh", "-ic", "alias")] = "new='x'\n"
        self.call("help", "aliases", "--refresh")
        self.assertEqual(self.titles("help aliases"), ["new"])  # the refresh replaced the memory

    def test_the_cache_expires(self):
        self.set_help(cache_seconds=600)
        self.search("help aliases")
        cache = json.loads((self.tmp / "cache.json").read_text())
        cache["aliases"]["time"] -= 1000
        (self.tmp / "cache.json").write_text(json.dumps(cache))
        before = len(self.runner.calls)
        self.search("help aliases")
        self.assertGreater(len(self.runner.calls), before)

    def test_a_damaged_cache_is_ignored(self):
        self.set_help(cache_seconds=600)
        (self.tmp / "cache.json").write_text("{not json")
        self.assertEqual(len(self.titles("help aliases")), 3)

    def test_fast_topics_are_never_cached(self):
        self.set_help(cache_seconds=600)
        self.search("help functions")
        self.assertFalse((self.tmp / "cache.json").exists())


class Terminal(HelpCase):
    def test_ml_help_lists_topics(self):
        code, out, _ = self.call("help")
        self.assertEqual(code, 0)
        self.assertIn("aliases", out)
        self.assertIn("Shell aliases", out)

    def test_ml_help_topic_and_filter(self):
        code, out, _ = self.call("help", "functions", "deploy")
        self.assertEqual(code, 0)
        self.assertIn("deploy", out)
        self.assertIn("rsync -av public/", out)  # one row: its whole detail is printed
        self.assertNotIn("build_site", out)

    def test_ml_help_json(self):
        code, out, _ = self.call("help", "aliases", "--json")
        self.assertEqual([r["title"] for r in json.loads(out)], ["gs", "ll", "name"])

    def test_nothing_matches(self):
        code, out, _ = self.call("help", "zzzz")
        self.assertEqual(code, 1)
        self.assertIn("Topics:", out)


class Report(HelpCase):
    def test_sections(self):
        logs = self.tmp / "logs"
        logs.mkdir()
        (logs / "app.log").write_text("\n".join(f"line {i}" for i in range(40)), encoding="utf-8")
        self.set_help()
        data = json.loads(Path(self.config).read_text())
        data["autostart"] = {"log_dir": str(logs)}
        Path(self.config).write_text(json.dumps(data))
        code, out, _ = self.call("report")
        self.assertEqual(code, 0)
        for heading in ("== python ==", "== packages", "== doctor ==", "== launch agent", "== logs in"):
            self.assertIn(heading, out)
        self.assertIn("<- the one Accessibility / Input Monitoring need", out)
        self.assertIn("line 39", out)
        self.assertNotIn("line 5\n", out)  # only the last 25 lines
        self.assertIn("launchctl", " ".join(self.runner.calls[-1]))

    def test_report_with_a_broken_configuration_still_prints_something(self):
        Path(self.config).write_text("{broken")
        code, out, _ = self.call("report")
        self.assertEqual(code, 1)
        self.assertIn("== doctor ==", out)
        self.assertIn("✘", out)


class ConfigHelp(unittest.TestCase):
    def parse(self, **section):
        return parse_config(support.good_config(help=section), "t.json")

    def test_defaults_and_paths(self):
        c = parse_config(support.good_config(), "t.json")
        self.assertEqual(c.help_word, "help")
        self.assertTrue(str(c.help_functions_file).endswith(".zsh_functions"))
        self.assertNotIn("~", str(c.help_scripts_folder))

    def test_words_must_differ(self):
        with self.assertRaisesRegex(ConfigError, "three different"):
            self.parse(word="run")
        with self.assertRaisesRegex(ConfigError, "help.word"):
            self.parse(word="two words")

    def test_types(self):
        with self.assertRaisesRegex(ConfigError, "help.cache_seconds"):
            self.parse(cache_seconds=-1)
        with self.assertRaisesRegex(ConfigError, "help.functions_file"):
            self.parse(functions_file=3)

    def test_a_quicklink_cannot_use_the_help_word(self):
        from myquicklinks import parse_quicklinks

        with self.assertRaises(ConfigError):
            parse_quicklinks([{"keyword": "help", "url": "https://x.test/{query}"}], reserved=("help",))


if __name__ == "__main__":
    unittest.main()
