"""Step 11: weather, the secret shown in the notification, secret-set VALUE / echo modes, private_notes + private_vault."""

import json
import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock

import support
from test_cli import CliCase
import mylauncher as M
from myactions import RunOptions, copy_secret, weather, weather_url
from myconfig import ConfigError, parse_config
from mysecret import build_secret_items, parse_secrets, set_notes, vault_text
from mytypes import Item

CURL = ("curl", "-s", "-f", "--max-time", "6", "https://wttr.in/?format=%c+%t")


class Weather(unittest.TestCase):
    def test_url_follows_the_curl_line_you_know(self):
        self.assertEqual(weather_url("", "%c+%t"), "https://wttr.in/?format=%c+%t")
        self.assertEqual(weather_url("New York", "%t"), "https://wttr.in/New+York?format=%t")

    def test_it_returns_one_line_and_notifies_it(self):
        runner = support.FakeRunner(outputs={CURL: "☀️ +21°C\n"})
        result = weather(Item("cmd:weather", "weather", "command", "weather"), runner=runner, options=RunOptions(notify_method="osascript"))
        self.assertEqual((result.ok, result.message), (True, "☀️ +21°C"))
        self.assertTrue(any("☀️ +21°C" in " ".join(c) for c in runner.calls[1:]))

    def test_offline_or_unknown_is_an_error_not_a_crash(self):
        for out, code in (("", 28), ("Unknown location; please try", 0), ("<html>", 0)):
            runner = support.FakeRunner(returncode=code, outputs={CURL: out})
            self.assertFalse(weather(Item("w", "w", "command", "weather"), runner=runner).ok)
        self.assertFalse(weather(Item("w", "w", "command", "weather"), runner=support.FakeRunner(error=FileNotFoundError())).ok)

    def test_dry_run_does_not_ask(self):
        runner = support.FakeRunner()
        self.assertTrue(weather(Item("w", "w", "command", "weather"), runner=runner, dry_run=True).ok)
        self.assertEqual(runner.calls, [])

    def test_setting_validated(self):
        with self.assertRaises(ConfigError):
            parse_config(support.good_config(["/tmp"], weather={"timeout_seconds": 0}), Path("x.json"))
        c = parse_config(support.good_config(["/tmp"], weather={"location": "Paris", "format": "%t"}), Path("x.json"))
        self.assertEqual((c.weather_location, c.weather_format), ("Paris", "%t"))


class WeatherCommand(CliCase):
    def test_typing_weather_runs_it_from_the_cli(self):
        cfg = support.good_config([self.tmp / "Applications"], commands=[{"id": "weather", "title": "weather", "action": "weather", "keywords": ["weather"]}], weather={"location": "Paris"})
        self.config = str(self.write_config(cfg))
        url = "https://wttr.in/Paris?format=%c+%t"
        runner = support.FakeRunner(outputs={("curl", "-s", "-f", "--max-time", "6", url): "⛅ +12°C"})
        code, out, _ = self.call("run", "--id", "cmd:weather", "--yes", "--json", runner=runner)
        self.assertEqual(code, 0)
        self.assertIn("+12°C", out)


SECRETS = 'GOOGLE=my_password_google\nGOOGLE.private_notes="""\nrecovery: 1234\nsecond line\n"""\nB=plain\n'


class Notes(unittest.TestCase):
    def test_parse_block_and_one_line_notes(self):
        found = {s.name: s for s in parse_secrets(SECRETS + 'C=x\nC.private_notes="a\\nb"\n')}
        self.assertEqual(found["GOOGLE"].notes, "recovery: 1234\nsecond line")
        self.assertEqual((found["GOOGLE"].value, found["B"].notes, found["C"].notes), ("my_password_google", "", "a\nb"))
        self.assertNotIn("GOOGLE.private_notes", found)

    def test_set_notes_replaces_and_removes(self):
        import tempfile, pathlib
        path = pathlib.Path(tempfile.mkdtemp()) / "s.env"
        path.write_text(SECRETS)
        set_notes(path, "GOOGLE", "new\nnotes")
        self.assertEqual({s.name: s.notes for s in parse_secrets(path.read_text())}["GOOGLE"], "new\nnotes")
        self.assertEqual(path.read_text().count("private_notes"), 1)
        set_notes(path, "GOOGLE", "")
        self.assertEqual({s.name: s.notes for s in parse_secrets(path.read_text())}["GOOGLE"], "")
        self.assertEqual([s.name for s in parse_secrets(path.read_text())], ["GOOGLE", "B"])


class SecretNotifyAndVault(CliCase):
    def setUp(self):
        super().setUp()
        self.secret = self.tmp / "s" / "secrets.env"
        self.secret.parent.mkdir()
        self.secret.write_text(SECRETS)
        os.chmod(self.secret, 0o600)
        self.set_config()

    def set_config(self, **secret):
        self.config = str(self.write_config(support.good_config([self.tmp / "Applications"], secret={"file": str(self.secret), **secret})))

    def test_vault_row_and_detail_have_the_notes(self):
        code, out, _ = self.call("search", "secret", "--json")
        rows = {r["title"]: r for r in json.loads(out)["results"]}
        self.assertIn("recovery: 1234", rows["private_vault"]["detail"])
        self.assertIn("private_notes:\nrecovery: 1234", rows["GOOGLE"]["detail"])
        self.assertTrue(rows["GOOGLE"]["subtitle"].startswith("📝"))
        self.assertIn("recovery: 1234", rows["all"]["detail"])
        code, out, _ = self.call("search", "secret vault", "--json")
        self.assertEqual([r["title"] for r in json.loads(out)["results"]], ["private_vault"])
        self.assertEqual([r["title"] for r in json.loads(self.call("search", "secret all", "--json")[1])["results"]][:1], ["all"])

    def test_secret_google_copies_and_the_notification_shows_the_value(self):
        runner = support.FakeRunner()
        code, out, _ = self.call("run", "secret GOOGLE", "--yes", "--json", runner=runner)
        self.assertEqual(runner.inputs[0], "my_password_google")
        self.assertTrue(any("my_password_google" in " ".join(c) for c in runner.calls[1:]), runner.calls)
        self.assertNotIn("my_password_google", out)  # the JSON for the window stays clean

    def test_the_value_can_be_kept_out_of_the_notification(self):
        self.set_config(notify_value=False)
        runner = support.FakeRunner()
        self.call("run", "secret GOOGLE", "--yes", "--json", runner=runner)
        self.assertFalse(any("my_password_google" in " ".join(c) for c in runner.calls[1:]))

    def test_the_all_row_is_not_put_in_a_notification(self):
        runner = support.FakeRunner()
        item = Item("secret:*all*", "all", "secret", "copy_secret", target="A = 1\nB = 2")
        copy_secret(item, runner=runner, options=RunOptions(notify_method="osascript"))
        self.assertFalse(any("A = 1" in " ".join(c) for c in runner.calls[1:]))


def notes_of(path):
    return {s.name: s.notes for s in parse_secrets(path.read_text())}['google']


class SecretSet(CliCase):
    def setUp(self):
        super().setUp()
        self.secret = self.tmp / "s" / "secrets.env"
        self.secret.parent.mkdir()
        self.calls = []
        self.patch = mock.patch.object(subprocess, "run", lambda c, check=False: self.calls.append(c) or type("R", (), {"returncode": 0})())
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def use(self, echo):
        self.config = str(self.write_config(support.good_config([self.tmp / "Applications"], secret={"file": str(self.secret), "input_echo": echo})))

    def test_value_on_the_command_line(self):
        self.use("hidden")
        code, out, _ = self.call("secret-set", "google", "my_password_google")
        self.assertEqual((code, self.calls[0][-2:]), (0, ["-w", "my_password_google"]))
        self.assertIn("google=keychain", self.secret.read_text())

    def test_hidden_lets_security_ask(self):
        self.use("hidden")
        self.call("secret-set", "google")
        self.assertEqual(self.calls[0][-1], "-w")

    def test_visible_asks_with_input(self):
        self.use("visible")
        code, _, _ = self.call("secret-set", "google", answers=["typed value"])
        self.assertEqual((code, self.calls[0][-1]), (0, "typed value"))

    def test_asterisks_use_the_star_reader(self):
        self.use("asterisks")
        with mock.patch.object(M, "read_with_stars", lambda prompt: "starred"):
            self.call("secret-set", "google")
        self.assertEqual(self.calls[0][-1], "starred")

    def test_empty_visible_value_is_not_saved(self):
        self.use("visible")
        self.assertEqual(self.call("secret-set", "google", answers=[""])[0], 1)
        self.assertEqual(self.calls, [])

    def test_notes_option_and_secret_notes_command(self):
        self.use("hidden")
        self.call("secret-set", "google", "pw", "--notes", "line1\\nline2")
        self.assertEqual(notes_of(self.secret), "line1\nline2")
        self.call("secret-notes", "google", "other\\nnotes")
        self.assertEqual(notes_of(self.secret), "other\nnotes")
        self.call("secret-notes", "google", "")
        self.assertEqual(notes_of(self.secret), "")

    def test_bad_echo_setting(self):
        with self.assertRaises(ConfigError):
            parse_config(support.good_config(["/tmp"], secret={"input_echo": "loud"}), Path("x.json"))


if __name__ == "__main__":
    unittest.main()


class Crash(unittest.TestCase):
    def test_ips_is_summarised(self):
        report = {"procName": "Python", "exception": {"type": "EXC_BREAKPOINT", "signal": "SIGTRAP"}, "termination": {"indicator": "Trace/BPT trap"},
                  "usedImages": [{"name": "libdispatch.dylib"}], "faultingThread": 0,
                  "threads": [{"triggered": True, "queue": "com.apple.main-thread", "frames": [{"imageIndex": 0, "symbol": "_dispatch_assert_queue_fail"}]}]}
        text = M.summarize_crash(json.dumps({"app": "x"}) + "\n" + json.dumps(report))
        self.assertIn("EXC_BREAKPOINT", text)
        self.assertIn("_dispatch_assert_queue_fail", text)

    def test_garbage_does_not_crash_the_summary(self):
        self.assertIn("hello", M.summarize_crash("hello\nworld"))
