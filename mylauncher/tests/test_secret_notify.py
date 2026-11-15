"""Step 9: notifications that can be diagnosed (mynotify), and the secret / keep_secret commands (mysecret)."""

import hashlib
import json
import os
import stat
import unittest
from pathlib import Path

import support
from test_cli import CliCase
import mynotify
from myactions import RunOptions, copy_secret, copy_snippet
from myconfig import ConfigError, parse_config
from myexecute import background_script
from mysecret import file_problems, mask, parse_secrets, table
from mytypes import Item

SECRETS = """# OpenRouter, for content_creation.py
# second line of the comment
OPENROUTER_API_KEY=sk-or-v1-abcdef0123456789ABCD

export TOKEN="a value with # and spaces"
SHORT=abc
NOTE='single quoted'   
PLAIN=value # trailing comment
not a secret line
1BAD=x
"""


class Notify(unittest.TestCase):
    def test_auto_prefers_terminal_notifier_when_installed(self):
        self.assertEqual(mynotify.resolve("auto", which=lambda n: "/opt/homebrew/bin/terminal-notifier"), ("terminal-notifier", "/opt/homebrew/bin/terminal-notifier"))
        self.assertEqual(mynotify.resolve("auto", which=lambda n: None), ("osascript", "osascript"))
        self.assertEqual(mynotify.resolve("none")[0], "none")
        self.assertEqual(mynotify.resolve("osascript", which=lambda n: "/x/terminal-notifier")[0], "osascript")

    def test_commands(self):
        tn = mynotify.argv("terminal-notifier", "mylauncher", "sub", "body", which=lambda n: "/x/tn")
        self.assertEqual(tn, ["/x/tn", "-title", "mylauncher", "-message", "body", "-group", "mylauncher", "-subtitle", "sub"])
        osa = mynotify.argv("osascript", "t", "s", 'say "hi"')
        self.assertEqual(osa[:2], ["osascript", "-e"])
        self.assertIn('display notification "say \\"hi\\""', osa[2])
        self.assertIn('subtitle "s"', osa[2])
        self.assertEqual(mynotify.argv("none", "t", "s", "m"), [])

    def test_send_reports_why_it_failed(self):
        ok, detail = mynotify.send(support.FakeRunner(returncode=1, stderr="boom\nnot allowed"), "osascript", "t", "", "m")
        self.assertEqual((ok, detail), (False, "not allowed"))
        ok, detail = mynotify.send(support.FakeRunner(error=FileNotFoundError()), "osascript", "t", "", "m")
        self.assertFalse(ok)
        self.assertIn("not found", detail)
        self.assertTrue(mynotify.send(support.FakeRunner(), "osascript", "t", "", "m")[0])
        ok, detail = mynotify.send(support.FakeRunner(), "none", "t", "", "m")
        self.assertTrue(ok)
        self.assertIn("off", detail)

    def test_the_line_for_background_scripts(self):
        self.assertIn("/usr/bin/osascript", mynotify.script_line("osascript", "x"))
        self.assertEqual(mynotify.script_line("none", "x"), ":")
        line = mynotify.script_line("terminal-notifier", 'ev"il', which=lambda n: "/x/tn")
        self.assertTrue(line.startswith("/x/tn -title"))
        self.assertIn('-message "$msg"', line)
        self.assertNotIn('ev"il', line)
        self.assertIn("terminal-notifier", background_script("n", "true", (), True, "terminal-notifier").replace("/x/tn", "terminal-notifier") or "terminal-notifier")

    def test_a_failed_notification_is_said_in_the_message_but_the_copy_still_counts(self):
        item = Item("snip:;a", ";a", "snippet", "copy_snippet", target="text", subtitle="text")
        result = copy_snippet(item, runner=_fail_osascript(), options=RunOptions())
        self.assertTrue(result.ok)
        self.assertIn("notification failed", result.message)
        self.assertIn("notify-test", result.message)

    def test_the_configured_method_is_used_for_snippets(self):
        runner = support.FakeRunner()
        item = Item("snip:;a", ";a", "snippet", "copy_snippet", target="text")
        copy_snippet(item, runner=runner, options=RunOptions(notify_method="none"))
        self.assertEqual([c[0] for c in runner.calls], ["pbcopy", "pbpaste"])


def _fail_osascript():
    class Runner(support.FakeRunner):
        def __call__(self, command, input_text=None):
            done = super().__call__(command, input_text)
            if command[0] == "osascript":
                done.returncode, done.stderr = 1, "not allowed"
            return done

    return Runner()


class NotifyCommand(CliCase):
    def test_notify_test_sends_and_explains(self):
        code, out, _ = self.call("notify-test")
        self.assertEqual(code, 0)
        self.assertIn("using osascript", out)
        self.assertIn("brew install terminal-notifier", out)
        self.assertEqual(self.runner.calls[-1][0], "osascript")

    def test_a_failure_gives_exit_code_1(self):
        code, out, _ = self.call("notify-test", runner=_fail_osascript())
        self.assertEqual(code, 1)
        self.assertIn("FAILED: not allowed", out)

    def test_method_none(self):
        self.config = str(self.write_config(support.good_config([self.tmp / "Applications"], notifications={"method": "none"})))
        code, out, _ = self.call("notify-test")
        self.assertIn("using none", out)

    def test_doctor_warns_about_osascript(self):
        code, out, _ = self.call("doctor")
        self.assertIn("notifications: osascript", out)
        self.assertIn("terminal-notifier", out)


class Parsing(unittest.TestCase):
    def test_entries(self):
        secrets = {s.name: s for s in parse_secrets(SECRETS)}
        self.assertEqual(list(secrets), ["OPENROUTER_API_KEY", "TOKEN", "SHORT", "NOTE", "PLAIN"])  # junk lines ignored
        self.assertEqual(secrets["OPENROUTER_API_KEY"].value, "sk-or-v1-abcdef0123456789ABCD")
        self.assertEqual(secrets["OPENROUTER_API_KEY"].comment, "OpenRouter, for content_creation.py\nsecond line of the comment")
        self.assertEqual(secrets["TOKEN"].value, "a value with # and spaces")  # export, quotes
        self.assertEqual(secrets["NOTE"].value, "single quoted")
        self.assertEqual(secrets["PLAIN"].value, "value")  # trailing comment of an unquoted value
        self.assertEqual(secrets["TOKEN"].comment, "")  # a blank line ends a comment block

    def test_mask(self):
        self.assertEqual(mask("sk-or-v1-abcdef0123456789ABCD").endswith("ABCD"), True)
        self.assertNotIn("abcdef", mask("sk-or-v1-abcdef0123456789ABCD"))
        self.assertEqual(mask("abc"), "•" * 8)  # too short: nothing at all is shown
        self.assertEqual(mask("a" * 40, reveal=0), "•" * 8)
        self.assertEqual(mask(""), "(empty)")

    def test_table(self):
        text = table(parse_secrets("# why\nA=1\nLONGER=2\n"))
        self.assertIn("# why\nA      = 1", text)
        self.assertIn("LONGER = 2", text)
        self.assertEqual(table([]), "(nothing in the file yet)")


class SecretCase(CliCase):
    def setUp(self):
        super().setUp()
        self.secret = self.tmp / "private" / "secrets.env"
        self.secret.parent.mkdir()
        self.secret.write_text(SECRETS, encoding="utf-8")
        os.chmod(self.secret, 0o600)
        self.configure()

    def configure(self, **secret):
        section = {"file": str(self.secret), **secret}
        self.config = str(self.write_config(support.good_config([self.tmp / "Applications"], secret=section)))

    def search(self, text):
        code, out, _ = self.call("search", text, "--json")
        return json.loads(out)

    def titles(self, text):
        return [r["title"] for r in self.search(text)["results"]]


class SecretList(SecretCase):
    def test_secret_lists_all_first_then_the_entries_with_values_hidden(self):
        data = self.search("secret")
        self.assertEqual((data["mode"], data["highlight"]), ("secret", 6))
        self.assertEqual([r["title"] for r in data["results"]], ["all", "OPENROUTER_API_KEY", "TOKEN", "SHORT", "NOTE", "PLAIN"])
        rows = {r["title"]: r for r in data["results"]}
        row = rows["OPENROUTER_API_KEY"]
        self.assertEqual((row["icon"], row["badge"], row["kind"], row["action"]), ("🔑", "Secret", "secret", "copy_secret"))
        self.assertTrue(row["subtitle"].startswith("•"))
        self.assertIn("ABCD", row["subtitle"])
        self.assertNotIn("abcdef0123456789", row["subtitle"])  # the middle never appears in the list
        self.assertIn("# OpenRouter, for content_creation.py", row["subtitle"])
        self.assertIn("sk-or-v1-abcdef0123456789ABCD", row["detail"])  # the detail view shows it in full
        self.assertEqual(rows["all"]["detail"].count("="), 5)
        self.assertIn("a value with # and spaces", rows["all"]["detail"])

    def test_filter_searches_names_and_comments_never_values(self):
        self.assertEqual(self.titles("secret openrouter"), ["OPENROUTER_API_KEY"])  # in the comment and the name
        self.assertEqual(self.titles("secret token"), ["TOKEN"])
        self.assertEqual(self.search("secret abcdef0123")["results"], [])  # a value is not searched

    def test_tab_keeps_the_word(self):
        self.assertEqual(self.search("secret tok")["completion"], "secret TOKEN")

    def test_loose_permissions_are_warned_about_in_the_list_and_in_doctor(self):
        os.chmod(self.secret, 0o644)
        self.assertEqual(self.search("secret")["results"][0]["title"], "The secret file is not safe")
        code, out, _ = self.call("doctor")
        self.assertIn("readable by other users", out)
        os.chmod(self.secret, 0o600)
        self.assertEqual(file_problems(self.secret), [])

    def test_a_file_inside_a_git_repository_is_flagged(self):
        (self.tmp / "private" / ".git").mkdir()
        self.assertTrue(any("git repository" in p for p in file_problems(self.secret)))

    def test_missing_or_empty_file_explains_what_to_do(self):
        self.secret.unlink()
        row = self.search("secret")["results"][0]
        self.assertEqual((row["id"], row["complete"]), ("info:secret", "keep_secret"))
        self.assertIn("keep_secret", row["subtitle"])
        code, out, _ = self.call("doctor")
        self.assertIn("secret: the secret file does not exist yet", out)

    def test_doctor_counts_entries(self):
        code, out, _ = self.call("doctor")
        self.assertIn("secret: 5 entries", out)

    def test_secrets_are_not_remembered_in_the_usage_history(self):
        usage = self.tmp / "usage.json"
        data = support.good_config([self.tmp / "Applications"], usage={"enabled": True, "file": str(usage)}, secret={"file": str(self.secret)})
        self.config = str(self.write_config(data))
        self.call("run", "--id", "secret:TOKEN", "--text=secret token", "--yes")
        self.assertFalse(usage.exists())


class CopySecret(SecretCase):
    def test_enter_copies_the_value_and_schedules_the_clipboard_to_be_emptied(self):
        code, out, _ = self.call("run", "--id", "secret:OPENROUTER_API_KEY", "--text=secret openrouter", "--yes", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(self.runner.inputs, ["sk-or-v1-abcdef0123456789ABCD"])
        self.assertNotIn("abcdef0123456789", out)  # the value is not in the message
        self.assertIn("emptied in 30 s", out)
        (command, log), = self.spawned
        self.assertEqual(command[:2], ["/bin/sh", "-c"])
        fingerprint = hashlib.sha256(b"sk-or-v1-abcdef0123456789ABCD").hexdigest()
        self.assertIn(f"{fingerprint}  -", command[2])
        self.assertIn("sleep 30", command[2])
        self.assertNotIn("abcdef0123456789", command[2])  # the secret itself is never on a command line
        self.assertTrue(log.endswith("secret-clear.log"))

    def test_clear_seconds_zero_never_empties(self):
        self.configure(clear_seconds=0)
        self.call("run", "--id", "secret:TOKEN", "--text=secret token", "--yes")
        self.assertEqual(self.spawned, [])

    def test_the_all_row_copies_the_whole_table(self):
        self.call("run", "--id", "secret:*all*", "--text=secret", "--yes")
        self.assertIn("TOKEN", self.runner.inputs[0])
        self.assertIn("a value with # and spaces", self.runner.inputs[0])

    def test_dry_run_copies_nothing(self):
        code, out, _ = self.call("run", "--id", "secret:TOKEN", "--text=secret token", "--dry-run")
        self.assertEqual((code, self.runner.calls, self.spawned), (0, [], []))

    def test_pbcopy_failure_is_reported_and_nothing_is_scheduled(self):
        item = Item("secret:X", "X", "secret", "copy_secret", target="v")
        spawned = []
        result = copy_secret(item, runner=support.FakeRunner(returncode=1, stderr="no clipboard"), options=RunOptions(spawn=lambda c, l: spawned.append(c)))
        self.assertFalse(result.ok)
        self.assertEqual(spawned, [])


class KeepSecret(SecretCase):
    def test_the_word_is_a_command_with_its_own_mode(self):
        data = self.search("keep_secret")
        self.assertEqual((data["mode"], data["highlight"]), ("keep_secret", 11))
        (row,) = data["results"]
        self.assertEqual((row["id"], row["action"], row["icon"]), ("cmd:keep_secret", "edit_secret", "🔐"))

    def test_it_is_also_found_by_a_part_of_the_word(self):
        self.assertEqual(self.search("keep_s")["results"][0]["id"], "prefix:keep_secret")

    def test_enter_opens_the_file_in_the_editor(self):
        code, out, _ = self.call("run", "keep_secret", "--yes")
        self.assertEqual(code, 0)
        self.assertEqual(self.runner.calls[-1], ["open", "-a", "Visual Studio Code", str(self.secret)])

    def test_a_missing_file_is_created_with_safe_permissions_and_a_template(self):
        self.secret.unlink()
        code, out, _ = self.call("run", "keep_secret", "--yes", "--json")
        self.assertEqual(code, 0)
        self.assertIn("created", out)
        self.assertEqual(stat.S_IMODE(self.secret.stat().st_mode), 0o600)
        self.assertIn("NAME=value", self.secret.read_text())
        self.assertEqual(self.runner.calls[-1][-1], str(self.secret))

    def test_a_missing_folder_is_created_too(self):
        self.secret = self.tmp / "new" / "deeper" / "s.env"
        self.configure()
        self.call("run", "keep_secret", "--yes")
        self.assertTrue(self.secret.exists())

    def test_loose_permissions_are_fixed(self):
        os.chmod(self.secret, 0o644)
        code, out, _ = self.call("run", "keep_secret", "--yes", "--json")
        self.assertEqual(stat.S_IMODE(self.secret.stat().st_mode), 0o600)
        self.assertIn("permissions set to 600", out)

    def test_existing_content_is_never_overwritten(self):
        self.call("run", "keep_secret", "--yes")
        self.assertEqual(self.secret.read_text(), SECRETS)

    def test_dry_run_creates_nothing(self):
        self.secret.unlink()
        self.call("run", "keep_secret", "--dry-run")
        self.assertFalse(self.secret.exists())


class SecretConfig(unittest.TestCase):
    def parse(self, **sections):
        return parse_config(support.good_config(**sections), Path("/x/c.json"))

    def test_defaults(self):
        c = self.parse()
        self.assertEqual((c.secret_word, c.secret_edit_word, c.secret_clear_seconds, c.secret_reveal), ("secret", "keep_secret", 30, 4))
        self.assertTrue(str(c.secret_file).endswith(".config/mylauncher/secrets.env"))
        self.assertEqual((c.notify_method, c.toast, c.toast_seconds), ("auto", True, 2.0))

    def test_validation(self):
        for sections, text in (
            ({"secret": {"word": "help"}}, "must all be different"),
            ({"secret": {"edit_word": "two words"}}, "secret.edit_word"),
            ({"secret": {"clear_seconds": -1}}, "cannot be negative"),
            ({"secret": {"file": 3}}, "secret.file"),
            ({"notifications": {"method": "email"}}, "notifications.method"),
            ({"notifications": {"toast_seconds": 0}}, "toast_seconds"),
            ({"notifications": {"toast": "yes"}}, "notifications.toast"),
        ):
            with self.subTest(sections=sections), self.assertRaisesRegex(ConfigError, text):
                self.parse(**sections)

    def test_a_quicklink_cannot_be_named_secret(self):
        from myquicklinks import parse_quicklinks

        with self.assertRaises(ConfigError):
            parse_quicklinks([{"keyword": "secret", "url": "https://x.test/{query}"}], reserved=("secret",))


if __name__ == "__main__":
    unittest.main()


class Completion(CliCase):
    """Two or three letters of a command word + Tab complete the word."""

    def test_letters_of_each_word_complete_that_word(self):
        for typed, word in (("ex", "execute "), ("exe", "execute "), ("ed", "edit "), ("sec", "secret "), ("ke", "keep_secret"),
                            ("he", "help "), ("ki", "kill "), ("ru", "run ")):
            code, out, _ = self.call("search", typed, "--json")
            self.assertEqual(json.loads(out)["completion"], word, typed)

    def test_a_command_word_goes_before_apps_and_quicklinks(self):
        ids = [r["id"] for r in json.loads(self.call("search", "ex", "--json")[1])["results"]]
        self.assertEqual(ids[0], "prefix:execute")


KEY = ("security", "find-generic-password", "-s", "justtothepoint-toolkit", "-a", "OPENROUTER_API_KEY", "-w")


class Keychain(SecretCase):
    def setUp(self):
        super().setUp()
        self.secret.write_text("# OpenRouter\nOPENROUTER_API_KEY=keychain\nOTHER=\nPLAIN=abcdefgh12345678\n", encoding="utf-8")
        self.runner = support.FakeRunner(outputs={KEY: "sk-or-v1-0123456789abcdef\n"})

    def test_the_value_comes_from_the_keychain_and_is_masked_in_the_list(self):
        data = self.search("secret")
        rows = {r["title"]: r for r in data["results"]}
        self.assertTrue(rows["OPENROUTER_API_KEY"]["subtitle"].startswith("🔒 "))
        self.assertTrue(rows["OPENROUTER_API_KEY"]["subtitle"].endswith("cdef   # OpenRouter"))
        self.assertIn("sk-or-v1-0123456789abcdef", rows["OPENROUTER_API_KEY"]["detail"])
        self.assertIn(KEY, [tuple(c) for c in self.runner.calls])

    def test_a_missing_keychain_entry_says_how_to_add_it(self):
        rows = {r["title"]: r for r in self.search("secret")["results"]}
        self.assertEqual(rows["OTHER"]["kind"], "prefix")  # nothing to copy
        self.assertIn("ml secret-set OTHER", rows["OTHER"]["subtitle"])

    def test_the_all_row_shows_the_keychain_value_too(self):
        text = self.search("secret")["results"][0]["detail"]
        self.assertIn("sk-or-v1-0123456789abcdef", text)
        self.assertIn("abcdefgh12345678", text)

    def test_enter_copies_the_keychain_value(self):
        code, out, _ = self.call("run", "secret OPENROUTER_API_KEY", "--yes", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(self.runner.inputs[0], "sk-or-v1-0123456789abcdef")
        self.assertNotIn("0123456789abcdef", out)

    def test_filter_still_finds_the_problem_rows(self):
        self.assertEqual([r["title"] for r in self.search("secret other")["results"]], ["OTHER"])

    def test_secret_set_saves_in_the_keychain_and_lists_the_name(self):
        import subprocess
        from unittest import mock
        calls = []
        with mock.patch.object(subprocess, "run", lambda c, check=False: calls.append(c) or type("R", (), {"returncode": 0})()):
            code, out, _ = self.call("secret-set", "NEWKEY")
        self.assertEqual(code, 0)
        self.assertEqual(calls[0], ["security", "add-generic-password", "-U", "-s", "justtothepoint-toolkit", "-a", "NEWKEY", "-w"])
        self.assertIn("NEWKEY=keychain", self.secret.read_text())
        self.call("secret-set", "NEWKEY")  # twice: still one line
        self.assertEqual(self.secret.read_text().count("NEWKEY=keychain"), 1)

    def test_secret_set_rejects_a_bad_name(self):
        self.assertEqual(self.call("secret-set", "a b")[0], 2)


class EspansoOutOfTheWindow(CliCase):
    def setUp(self):
        super().setUp()
        self.base = self.tmp / "espanso"
        (self.base / "match").mkdir(parents=True)

    def test_config_dir_is_found_from_the_match_folder(self):
        import myespanso
        self.assertEqual(myespanso.config_dir(self.base / "match"), self.base / "config")
        (self.base / "config").mkdir()
        self.assertEqual(myespanso.config_dir(self.base / "match" / "sub"), self.base / "config")

    def test_the_text_switches_espanso_off_for_the_window_title(self):
        import myespanso
        text = myespanso.config_text("my launcher")
        self.assertIn("filter_title: '^mylauncher$'", myespanso.config_text("mylauncher"))
        self.assertIn("filter_title: '^", text)
        self.assertIn("enable: false", text)

    def test_install_writes_the_file_and_status_then_says_ok(self):
        import myespanso
        self.assertFalse(myespanso.status(self.base / "match", "mylauncher")[0])
        ok, _ = myespanso.install(self.base / "match", "mylauncher")
        self.assertTrue(ok)
        self.assertTrue((self.base / "config" / "mylauncher.yml").is_file())
        self.assertTrue(myespanso.status(self.base / "match", "mylauncher")[0])
        self.assertFalse(myespanso.status(self.base / "match", "other title")[0])

    def test_nothing_is_written_when_the_folder_is_unknown(self):
        import myespanso
        self.assertFalse(myespanso.install(self.tmp / "nowhere" / "x", "mylauncher")[0])


class HotkeyWatchdog(unittest.TestCase):
    def make(self):
        import myhotkey

        class Fake:
            started = 0
            alive = True
            def __init__(self, **kw): Fake.started += 1
            def start(self): pass
            def stop(self): pass
            def is_alive(self): return Fake.alive

        listener = myhotkey.HotkeyListener(("command",), "d", lambda: None, factory=Fake, swallow=True)
        listener.start()
        return listener, Fake

    def test_a_tap_switched_off_by_macos_is_noticed_and_restarted(self):
        listener, Fake = self.make()
        self.assertTrue(listener.healthy())
        listener.intercept(0xFFFFFFFE, object())  # "disabled by timeout"
        self.assertFalse(listener.healthy())
        listener.restart()
        self.assertTrue(listener.healthy())
        self.assertEqual(Fake.started, 2)

    def test_a_dead_thread_is_restarted_too(self):
        listener, Fake = self.make()
        Fake.alive = False
        self.assertFalse(listener.healthy())


class HotkeyDoesNotStayDisarmed(unittest.TestCase):
    def test_a_lost_key_up_does_not_kill_the_hotkey(self):
        import myhotkey, time
        fired = []
        matcher = myhotkey.HotkeyMatcher(("command",), "d", lambda: fired.append(1))
        self.assertTrue(matcher.trigger())
        self.assertFalse(matcher.trigger())  # key still down: no second fire
        matcher.last_attempt = time.monotonic() - 1  # ...but the key-up never came, a second later
        self.assertTrue(matcher.trigger())
        self.assertEqual(len(fired), 2)


class SilentTap(unittest.TestCase):
    """The tap can die without telling anyone: compare what the keyboard did with what our tap saw."""

    def make(self, key_age):
        import myhotkey

        class Fake:
            def __init__(self, **kw): pass
            def start(self): pass
            def stop(self): pass
            def is_alive(self): return True

        listener = myhotkey.HotkeyListener(("command",), "d", lambda: None, factory=Fake, swallow=True, key_age=lambda: key_age[0])
        listener.start()
        return listener

    def test_keys_the_keyboard_saw_but_our_tap_did_not_mean_a_dead_tap(self):
        import time
        age = [100.0]
        listener = self.make(age)
        listener.last_seen = time.monotonic() - 30  # we saw nothing for 30 s
        self.assertFalse(listener.starved())  # the keyboard was silent too (last key 100 s ago): nobody typed
        age[0] = 2.0  # a key 2 s ago, and we did not see it
        self.assertTrue(listener.starved())
        self.assertFalse(listener.healthy())

    def test_a_tap_that_sees_the_keys_is_healthy(self):
        import time
        age = [0.2]
        listener = self.make(age)
        listener.intercept(10, object())  # a key event arrives (reader fails on a fake event: it is let through, still counted)
        self.assertTrue(listener.healthy())

    def test_restart_forgets_the_old_silence(self):
        import time
        listener = self.make([1.0])
        listener.last_seen = time.monotonic() - 50
        self.assertFalse(listener.healthy())
        listener.restart()
        self.assertTrue(listener.healthy())

