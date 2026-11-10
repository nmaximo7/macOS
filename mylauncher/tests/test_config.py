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

    def test_tilde_is_expanded(self):
        config = load_config(support.REAL_CONFIG)
        self.assertTrue(all("~" not in str(f) for f in config.app_folders))


class Reading(support.TempDirCase):
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
