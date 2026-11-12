"""myconfig.py: reading and checking conf/myconfiguration.json."""

import json
import unittest
from pathlib import Path

import support
from myconfig import ConfigError, find_config_path, load_config, parse_config


class RealFile(unittest.TestCase):
    def test_the_configuration_that_ships_with_the_project_is_valid(self):
        config = load_config(support.REAL_CONFIG)
        self.assertEqual(config.hotkey_modifiers, ("command",))
        self.assertEqual(config.hotkey_key, "d")
        self.assertEqual((config.window_width, config.window_font_size), (640, 20))
        self.assertEqual([c.id for c in config.commands], ["shutdown"])
        self.assertTrue(config.commands[0].confirm)

    def test_the_shipped_quicklinks_are_loaded_with_the_configuration(self):
        config = load_config(support.REAL_CONFIG)
        self.assertEqual([l.keyword for l in config.quicklinks], ["jttp", "google", "yt"])

    def test_tilde_is_expanded(self):
        config = load_config(support.REAL_CONFIG)
        self.assertTrue(all("~" not in str(f) for f in config.app_folders))


class Reading(support.TempDirCase):
    def test_quicklinks_file_next_to_the_configuration_is_read(self):
        self.write_quicklinks([{"keyword": "x", "url": "https://x.test/?q={query}"}])
        config = load_config(self.write_config(support.good_config()))
        self.assertEqual([l.keyword for l in config.quicklinks], ["x"])

    def test_a_wrong_quicklinks_file_is_a_configuration_error(self):
        self.write_quicklinks([{"keyword": "x"}])
        with self.assertRaises(ConfigError):
            load_config(self.write_config(support.good_config()))

    def test_a_quicklink_cannot_use_the_kill_word(self):
        self.write_quicklinks([{"keyword": "kill", "url": "https://x.test"}])
        with self.assertRaises(ConfigError) as ctx:
            load_config(self.write_config(support.good_config()))
        self.assertIn("reserved", str(ctx.exception))

    def test_missing_file(self):
        with self.assertRaises(ConfigError) as ctx:
            load_config(self.tmp / "nope.json")
        self.assertIn("not found", str(ctx.exception))

    def test_invalid_json_says_where(self):
        path = self.tmp / "bad.json"
        path.write_text('{\n  "hotkey": {,\n}', encoding="utf-8")
        with self.assertRaises(ConfigError) as ctx:
            load_config(path)
        self.assertIn("line 2", str(ctx.exception))

    def test_a_list_instead_of_an_object(self):
        with self.assertRaises(ConfigError):
            parse_config([], Path("x"))


class Checking(unittest.TestCase):
    """Every wrong value must produce a message that names the setting."""

    def assertBad(self, data, *words):
        with self.assertRaises(ConfigError) as ctx:
            parse_config(data, Path("x.json"))
        for word in words:
            self.assertIn(word, str(ctx.exception))

    def test_a_valid_configuration_passes(self):
        config = parse_config(support.good_config(), Path("x.json"))
        self.assertEqual(config.max_results, 8)
        self.assertEqual(config.app_exclude, ())

    def test_missing_sections(self):
        for section in ("hotkey", "apps", "search"):
            data = support.good_config()
            del data[section]
            with self.subTest(section=section):
                self.assertBad(data, section)
        data = support.good_config()
        del data["commands"]
        self.assertBad(data, "commands")

    def test_hotkey_modifier_must_be_known(self):
        data = support.good_config(hotkey={"modifiers": ["cmd"], "key": "d"})
        self.assertBad(data, "hotkey.modifiers", "cmd")

    def test_hotkey_modifiers_are_case_insensitive(self):
        config = parse_config(support.good_config(hotkey={"modifiers": ["Command", "SHIFT"], "key": "D"}), Path("x"))
        self.assertEqual((config.hotkey_modifiers, config.hotkey_key), (("command", "shift"), "d"))

    def test_hotkey_key_is_one_character(self):
        self.assertBad(support.good_config(hotkey={"modifiers": [], "key": "dd"}), "hotkey.key")

    def test_types_are_checked(self):
        bad_search = {"max_results": "8", "ignore_accents": True, "fuzzy": True}
        self.assertBad(support.good_config(search=bad_search), "search.max_results", "number")
        bad_search = {"max_results": True, "ignore_accents": True, "fuzzy": True}
        self.assertBad(support.good_config(search=bad_search), "search.max_results")  # True is not a number
        bad_search = {"max_results": 8, "ignore_accents": "yes", "fuzzy": True}
        self.assertBad(support.good_config(search=bad_search), "search.ignore_accents", "true or false")
        self.assertBad(support.good_config(apps={"folders": "/Applications"}), "apps.folders", "list")
        self.assertBad(support.good_config(apps={"folders": [3]}), "apps.folders[0]")

    def test_max_results_at_least_one(self):
        bad_search = {"max_results": 0, "ignore_accents": True, "fuzzy": True}
        self.assertBad(support.good_config(search=bad_search), "at least 1")

    def test_command_checks(self):
        base = {"id": "shutdown", "title": "Shutdown", "action": "shutdown"}
        self.assertBad(support.good_config(commands=[{**base, "action": "explode"}]), "commands[0].action", "explode")
        self.assertBad(support.good_config(commands=[base, base]), "twice")
        self.assertBad(support.good_config(commands=[{"title": "x", "action": "shutdown"}]), "commands[0].id")
        self.assertBad(support.good_config(commands=["shutdown"]), "commands[0]")

    def test_optional_command_fields_have_defaults(self):
        config = parse_config(
            support.good_config(commands=[{"id": "shutdown", "title": "Shutdown", "action": "shutdown"}]), Path("x")
        )
        self.assertEqual((config.commands[0].keywords, config.commands[0].confirm), ((), False))

    def test_window_section_is_optional_and_checked(self):
        defaults = parse_config(support.good_config(), Path("x"))
        self.assertEqual((defaults.window_title, defaults.window_width), ("mylauncher", 640))
        custom = parse_config(support.good_config(window={"width": 800, "title": "go"}), Path("x"))
        self.assertEqual((custom.window_title, custom.window_width, custom.window_font_size), ("go", 800, 20))
        self.assertBad(support.good_config(window={"width": "wide"}), "window.width")
        self.assertBad(support.good_config(window={"width": 0}), "window.width")
        self.assertBad(support.good_config(window={"top_offset": -5}), "window.top_offset")
        self.assertBad(support.good_config(window=[]), "window")

    def test_new_sections_have_defaults(self):
        c = parse_config(support.good_config(), Path("/conf/myconfiguration.json"))
        self.assertEqual(c.quicklinks_path, Path("/conf/quicklinks.json"))  # relative: next to the configuration file
        self.assertEqual((c.kill_word, c.kill_grace_seconds, c.kill_auto_force, c.kill_protected), ("kill", 5, False, ("python",)))
        self.assertEqual((c.menubar_enabled, c.menubar_title, c.menubar_hide_dock), (True, "⌘", False))
        self.assertEqual((c.usage_boost_per_use, c.usage_max_boost), (2, 10))

    def test_quicklinks_file_setting(self):
        c = parse_config(support.good_config(quicklinks={"file": "/abs/links.json"}), Path("/conf/c.json"))
        self.assertEqual(c.quicklinks_path, Path("/abs/links.json"))
        c = parse_config(support.good_config(quicklinks={"file": "sub/l.json"}), Path("/conf/c.json"))
        self.assertEqual(c.quicklinks_path, Path("/conf/sub/l.json"))
        self.assertBad(support.good_config(quicklinks={"file": 3}), "quicklinks.file")

    def test_usage_checks(self):
        self.assertBad(support.good_config(usage={"max_boost": 20}), "max_boost", "better match")
        self.assertBad(support.good_config(usage={"max_boost": -1}), "max_boost")
        self.assertBad(support.good_config(usage={"boost_per_use": -1}), "boost_per_use")
        self.assertBad(support.good_config(usage={"enabled": "yes"}), "usage.enabled")
        self.assertBad(support.good_config(usage=[]), "usage")

    def test_kill_checks(self):
        self.assertBad(support.good_config(kill={"word": "two words"}), "kill.word")
        self.assertBad(support.good_config(kill={"word": ""}), "kill.word")
        self.assertBad(support.good_config(kill={"grace_seconds": -1}), "grace_seconds")
        self.assertBad(support.good_config(kill={"auto_force": 1}), "kill.auto_force")
        c = parse_config(support.good_config(kill={"word": "QUIT", "protected": ["Python", "Finder"]}), Path("x"))
        self.assertEqual((c.kill_word, c.kill_protected), ("quit", ("python", "finder")))

    def test_menubar_checks(self):
        self.assertBad(support.good_config(menubar={"enabled": "yes"}), "menubar.enabled")
        self.assertBad(support.good_config(menubar={"title": 5}), "menubar.title")
        self.assertBad(support.good_config(menubar={"hide_dock_icon": "no"}), "menubar.hide_dock_icon")

    def test_expander_is_off_unless_a_folder_is_given(self):
        c = parse_config(support.good_config(), Path("x"))
        self.assertFalse(c.expander_enabled)
        c = parse_config(support.good_config(expander={"folder": "  "}), Path("x"))
        self.assertFalse(c.expander_enabled)
        c = parse_config(support.good_config(expander={"folder": "~/Espanso"}), Path("x"))
        self.assertTrue(c.expander_enabled)
        self.assertNotIn("~", str(c.expander_folder))
        self.assertEqual((c.expander_strip_cursor, c.expander_notify), (True, True))
        c = parse_config(support.good_config(expander={"folder": "/e", "enabled": False}), Path("x"))
        self.assertFalse(c.expander_enabled)

    def test_expander_checks(self):
        self.assertBad(support.good_config(expander={"folder": 3}), "expander.folder")
        self.assertBad(support.good_config(expander={"folder": "/e", "enabled": "yes"}), "expander.enabled")
        self.assertBad(support.good_config(expander={"folder": "/e", "notification": 1}), "expander.notification")
        self.assertBad(support.good_config(expander={"folder": "/e", "strip_cursor_marker": "no"}), "expander.strip_cursor_marker")
        self.assertBad(support.good_config(expander=[]), "expander")

    def test_the_shipped_configuration_points_at_the_espanso_folder(self):
        c = load_config(support.REAL_CONFIG)
        self.assertTrue(c.expander_enabled)
        self.assertTrue(str(c.expander_folder).endswith("macOS/Espanso/Library/Application Support"))

    def test_exclude_is_lower_cased(self):
        data = support.good_config(apps={"folders": [], "exclude": ["Boot Camp Assistant"]})
        self.assertEqual(parse_config(data, Path("x")).app_exclude, ("boot camp assistant",))


class WhichFile(unittest.TestCase):
    def test_explicit_beats_environment_beats_default(self):
        env = {"MYLAUNCHER_CONF": "/from/env.json"}
        self.assertEqual(find_config_path("/explicit.json", env), Path("/explicit.json"))
        self.assertEqual(find_config_path(None, env), Path("/from/env.json"))
        default = find_config_path(None, {})
        self.assertEqual(default.name, "myconfiguration.json")
        self.assertEqual(default.parent.name, "conf")

    def test_default_points_at_the_shipped_file(self):
        self.assertEqual(find_config_path(None, {}), support.REAL_CONFIG)


if __name__ == "__main__":
    unittest.main()
