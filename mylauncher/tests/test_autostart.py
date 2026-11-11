"""app/myautostart.py: the launch agent (fake launchctl, fake home folder)."""

import plistlib
import unittest
from pathlib import Path
from types import SimpleNamespace

import support
from myautostart import APP_SCRIPT, Autostart, build_plist, main, plist_path
from myconfig import parse_config


class FakeLaunchctl:
    """Pretends to be launchctl: remembers commands; `loaded` says whether the agent is loaded."""

    def __init__(self, loaded=False, bootstrap_fails=False, print_output=""):
        self.calls, self.loaded, self.bootstrap_fails, self.print_output = [], loaded, bootstrap_fails, print_output

    def __call__(self, command):
        self.calls.append(command[1:])
        verb = command[1]
        if verb == "print":
            return SimpleNamespace(returncode=0 if self.loaded else 113, stdout=self.print_output, stderr="")
        if verb == "bootstrap":
            if self.bootstrap_fails:
                return SimpleNamespace(returncode=5, stdout="", stderr="Input/output error")
            self.loaded = True
        if verb == "bootout":
            self.loaded = False
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def verbs(self):
        return [c[0] for c in self.calls]


class Base(support.TempDirCase):
    def setUp(self):
        super().setUp()
        data = support.good_config(autostart={"label": "com.test.launcher", "log_dir": str(self.tmp / "logs")})
        self.config_file = self.write_config(data)
        self.config = parse_config(data, self.config_file)
        self.launchctl = FakeLaunchctl()

    def auto(self, **kw):
        return Autostart(self.config, self.config_file, python="/venv/bin/python", runner=self.launchctl, home=self.tmp, uid=501, **kw)


class Building(Base):
    def test_plist_content(self):
        agent = build_plist(self.config, "/venv/bin/python", self.config_file)
        self.assertEqual(agent["Label"], "com.test.launcher")
        self.assertEqual(agent["ProgramArguments"][:2], ["/venv/bin/python", str(APP_SCRIPT)])
        self.assertEqual(agent["ProgramArguments"][2], "--config")
        self.assertTrue(agent["RunAtLoad"])
        self.assertEqual(agent["LimitLoadToSessionType"], "Aqua")
        self.assertEqual(agent["KeepAlive"], {"SuccessfulExit": False})
        self.assertEqual(agent["EnvironmentVariables"], {"PYTHONUNBUFFERED": "1"})
        self.assertTrue(agent["StandardOutPath"].endswith("mylauncher.log"))

    def test_keep_alive_can_be_switched_off(self):
        data = support.good_config(autostart={"keep_alive": False})
        agent = build_plist(parse_config(data, Path("x")), "p", Path("x"))
        self.assertNotIn("KeepAlive", agent)

    def test_xml_round_trip(self):
        data = plistlib.loads(self.auto().plist_bytes())
        self.assertEqual(data["Label"], "com.test.launcher")

    def test_file_location_and_names(self):
        a = self.auto()
        self.assertEqual(plist_path(self.config, self.tmp), self.tmp / "Library/LaunchAgents/com.test.launcher.plist")
        self.assertEqual((a.domain, a.service), ("gui/501", "gui/501/com.test.launcher"))


class Install(Base):
    def test_install_writes_the_file_and_bootstraps(self):
        lines = self.auto().install()
        a = self.auto()
        self.assertEqual(plistlib.loads(a.file.read_bytes())["Label"], "com.test.launcher")
        self.assertTrue((self.tmp / "logs").is_dir())
        self.assertIn(["bootstrap", "gui/501", str(a.file)], self.launchctl.calls)
        self.assertTrue(any("/venv/bin/python" in line for line in lines))  # the permissions hint
        self.assertTrue(any("Input Monitoring" in line for line in lines))

    def test_reinstall_unloads_first(self):
        self.launchctl.loaded = True
        self.auto().install()
        self.assertEqual(self.launchctl.verbs(), ["print", "bootout", "bootstrap"])

    def test_dry_run_changes_nothing(self):
        lines = self.auto(dry_run=True).install()
        self.assertFalse(self.auto().file.exists())
        self.assertFalse((self.tmp / "logs").exists())
        self.assertEqual(self.launchctl.calls, [])
        self.assertTrue(any("would run: launchctl bootstrap" in line for line in lines))

    def test_bootstrap_failure_is_reported(self):
        self.launchctl.bootstrap_fails = True
        with self.assertRaises(RuntimeError) as ctx:
            self.auto().install()
        self.assertIn("Input/output error", str(ctx.exception))

    def test_no_launchctl_means_not_a_mac(self):
        def missing(command):
            raise FileNotFoundError()

        with self.assertRaises(RuntimeError) as ctx:
            Autostart(self.config, self.config_file, runner=missing, home=self.tmp, uid=501).install()
        self.assertIn("macOS", str(ctx.exception))


class Other(Base):
    def test_uninstall(self):
        a = self.auto()
        a.install()
        lines = self.auto().uninstall()
        self.assertFalse(a.file.exists())
        self.assertFalse(self.launchctl.loaded)
        self.assertTrue(any("deleted" in line for line in lines))

    def test_uninstall_when_nothing_is_there(self):
        self.assertEqual(self.auto().uninstall(), ["nothing to uninstall"])

    def test_restart(self):
        self.auto().restart()
        self.assertEqual(self.launchctl.calls, [["kickstart", "-k", "gui/501/com.test.launcher"]])

    def test_status_not_loaded(self):
        self.assertIn("not loaded", self.auto().status()[-1])

    def test_status_parses_launchctl_print(self):
        self.launchctl.loaded = True
        self.launchctl.print_output = "com.test.launcher = {\n\tstate = running\n\tpid = 4242\n\truns = 1\n}"
        text = "\n".join(self.auto().status())
        self.assertIn("state running", text)
        self.assertIn("pid 4242", text)

    def test_logs(self):
        a = self.auto()
        self.assertIn("no log yet", a.logs()[0])
        (self.tmp / "logs").mkdir()
        a.log_file.write_text("\n".join(f"line {i}" for i in range(100)))
        self.assertEqual(a.logs(3), ["line 97", "line 98", "line 99"])


class CommandLine(Base):
    def run_main(self, *args):
        import contextlib
        import io

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main([*args, "--config", str(self.config_file)], runner=self.launchctl, home=self.tmp, uid=501, python="/venv/bin/python")
        return code, out.getvalue(), err.getvalue()

    def test_show_prints_the_file_and_changes_nothing(self):
        code, out, _ = self.run_main("show")
        self.assertEqual(code, 0)
        self.assertIn("<key>RunAtLoad</key>", out)
        self.assertEqual(self.launchctl.calls, [])

    def test_install_then_status(self):
        self.assertEqual(self.run_main("install")[0], 0)
        code, out, _ = self.run_main("status")
        self.assertEqual(code, 0)
        self.assertIn("loaded", out)

    def test_errors_exit_1_and_bad_config_exit_2(self):
        self.launchctl.bootstrap_fails = True
        self.assertEqual(self.run_main("install")[0], 1)
        self.config_file.write_text("{}")
        self.assertEqual(self.run_main("show")[0], 2)


class Config(unittest.TestCase):
    def test_autostart_section_defaults_and_checks(self):
        defaults = parse_config(support.good_config(), Path("x"))
        self.assertEqual(defaults.autostart_label, "com.mylauncher.app")
        self.assertTrue(defaults.autostart_keep_alive)
        self.assertNotIn("~", str(defaults.autostart_log_dir))
        for bad in ({"label": "has space"}, {"label": ""}, {"label": 3}, {"keep_alive": "yes"}, {"log_dir": 5}):
            with self.subTest(bad=bad), self.assertRaises(Exception):
                parse_config(support.good_config(autostart=bad), Path("x"))


if __name__ == "__main__":
    unittest.main()
