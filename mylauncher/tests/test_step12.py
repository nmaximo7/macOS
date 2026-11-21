"""Step 12: about, timer, explain, deep_study, describe_image (and prompts.json)."""

import base64
import io
import json
import subprocess
import tempfile
import unittest
import urllib.error
from pathlib import Path

import support
from test_cli import CliCase
import mylauncher as M
import myassistant
import myversion
from myactions import RunOptions, timer
from myconfig import ConfigError, parse_config
from mytimer import format_duration, parse_duration, timer_script
from mytypes import Item


class Durations(unittest.TestCase):
    def test_what_people_type(self):
        cases = {"90": 90, "90s": 90, "5m": 300, "1h30m": 5400, "1:30": 90, "1:02:03": 3723, "1.5m": 90, "2 minutes": 120, "10 min 5 s": 605, "1h": 3600}
        for text, seconds in cases.items():
            self.assertEqual(parse_duration(text), seconds, text)

    def test_what_is_not_a_time(self):
        for text in ("", "abc", "5x", "0", "100h", "1h 30", "-5", "1:2:3:4", "1:x", "m5"):
            self.assertIsNone(parse_duration(text), text)

    def test_format(self):
        self.assertEqual(format_duration(5430), "1h 30m 30s")
        self.assertEqual(format_duration(90), "1m 30s")

    def test_the_script_is_valid_shell_and_waits_by_the_clock(self):
        script = timer_script(90, "osascript", "/System/Library/Sounds/Glass.aiff", 3)
        self.assertEqual(subprocess.run(["sh", "-n", "-c", script]).returncode, 0)
        self.assertIn("date +%s", script)
        self.assertIn("afplay", script)
        self.assertNotIn("afplay", timer_script(5, "none", "x.aiff", 0))


class TimerAction(CliCase):
    def test_action_spawns_the_script(self):
        spawned = []
        options = RunOptions(notify_method="osascript", spawn=lambda c, log: spawned.append((c, str(log))), log_dir=Path(self.tmp), timer_folder=str(self.tmp / "timers"))
        result = timer(Item("timer:90", "Timer", "timer", "timer", target="90"), options=options)
        self.assertTrue(result.ok)
        self.assertIn("1m 30s", result.message)
        self.assertIn("+ 90 ))", spawned[0][0][-1])

    def test_cli_timer(self):
        self.config = str(self.write_config(support.good_config([self.tmp / "Applications"])))
        code, out, _ = self.call("timer", "1m30s")
        self.assertEqual(code, 0)
        self.assertIn("+ 90 ))", self.spawned[0][0][-1])
        self.assertEqual(self.call("timer", "banana")[0], 2)
        self.assertEqual(len(self.spawned), 1)

    def test_typing_in_the_launcher(self):
        self.config = str(self.write_config(support.good_config([self.tmp / "Applications"])))
        rows = json.loads(self.call("search", "timer 5m", "--json")[1])["results"]
        self.assertEqual((rows[0]["id"], rows[0]["title"]), ("timer:300", "Timer: 5m"))
        code, out, _ = self.call("run", "--id", "timer:300", "--text", "timer 5m", "--yes", "--json")
        self.assertEqual(code, 0)
        self.assertIn("+ 300 ))", self.spawned[0][0][-1])
        for typed in ("timer ", "timer soon"):
            hint = json.loads(self.call("search", typed, "--json")[1])["results"][-1]
            self.assertEqual(hint["id"], "info:timer")


class About(CliCase):
    def setUp(self):
        super().setUp()
        self.config = str(self.write_config(support.good_config([self.tmp / "Applications"])))

    def test_about_rows(self):
        hint = json.loads(self.call("search", "about", "--json")[1])["results"][0]
        self.assertEqual((hint["id"], hint["complete"]), ("prefix:about", "about "))
        rows = {r["title"]: r for r in json.loads(self.call("search", "about ", "--json")[1])["results"]}
        self.assertTrue({"Version", "Python", "Hotkey", "Files"} <= set(rows))
        self.assertTrue(next(iter(rows)).startswith("all"))
        self.assertIn(myversion.VERSION, rows["Version"]["subtitle"])
        code, out, _ = self.call("about")
        self.assertEqual(code, 0)
        self.assertIn(myversion.VERSION, out)
        self.assertIn("fingerprint", out)
        self.assertIn("Python", out)
        self.assertIn("Hotkey", out)

    def test_about_json(self):
        data = json.loads(self.call("about", "--json")[1])
        names = {d["name"] for d in data}
        self.assertTrue({"Version", "Python", "Configuration", "Hotkey", "Ollama"} <= names)

    def test_version_flag_shows_the_fingerprint(self):
        out = io.StringIO()
        from contextlib import redirect_stdout
        with redirect_stdout(out), self.assertRaises(SystemExit):
            M.main(["--version"])
        self.assertIn(myversion.VERSION, out.getvalue())
        self.assertIn("fingerprint", out.getvalue())

    def test_fingerprint_changes_with_the_files(self):
        root = Path(tempfile.mkdtemp())
        (root / "cli").mkdir()
        (root / "app").mkdir()
        (root / "cli" / "a.py").write_text("x = 1")
        first = myversion.fingerprint(root)
        (root / "cli" / "a.py").write_text("x = 2")
        second = myversion.fingerprint(root)
        self.assertEqual(first[0], 1)
        self.assertNotEqual(first[1], second[1])


class Response:
    """What urlopen returns: iterate over the lines, usable in `with`."""

    def __init__(self, chunks):
        self.lines = [(json.dumps(c) + "\n").encode() for c in chunks]

    def __iter__(self):
        return iter(self.lines)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def answer(*words, done=True):
    return Response([{"response": w} for w in words] + ([{"response": "", "done": True}] if done else []))


class Prompts(unittest.TestCase):
    def write(self, data):
        path = Path(tempfile.mkdtemp()) / "prompts.json"
        path.write_text(json.dumps(data))
        return path

    def test_lists_are_joined_and_notes_ignored(self):
        prompts = myassistant.load_prompts(self.write({"_help": "x", "explain": ["a {topic}", "b"]}))
        self.assertEqual(prompts, {"explain": "a {topic}\nb"})
        self.assertEqual(myassistant.build_prompt(prompts, "explain", " light "), "a light\nb")

    def test_the_shipped_file_is_good(self):
        prompts = myassistant.load_prompts(Path(__file__).resolve().parent.parent / "conf" / "prompts.json")
        for kind in ("explain", "deep_study"):
            self.assertIn("{topic}", prompts[kind])
        self.assertIn("what is visible", prompts["describe_image"].replace("what is visible", "what is visible"))
        self.assertIn("beginner", prompts["explain"])

    def test_problems_are_clear(self):
        with self.assertRaises(ConfigError):
            myassistant.load_prompts(self.write({"explain": 5}))
        with self.assertRaises(ConfigError):
            myassistant.load_prompts(Path("/no/such/prompts.json"))
        with self.assertRaises(myassistant.AssistantError):
            myassistant.build_prompt({"explain": "no placeholder"}, "explain", "x")


class Ollama(CliCase):
    def setUp(self):
        super().setUp()
        cfg = support.good_config([self.tmp / "Applications"], ollama={"model": "qwen3.8:27b", "prompts_file": "prompts.json"})
        path = self.write_config(cfg)
        (path.parent / "prompts.json").write_text(json.dumps({
            "explain": "EXPLAIN {topic}", "deep_study": ["DEEP", "{topic}"], "describe_image": "DESCRIBE"}))
        self.config = str(path)
        self.requests = []

    def opener(self, *responses):
        queue = list(responses)

        def open_(request, timeout=0):
            self.requests.append((request, timeout))
            item = queue.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        return open_

    def body(self, n=0):
        return json.loads(self.requests[n][0].data)

    def test_explain_streams_the_answer(self):
        code, out, _ = self.call("explain", "photosynthesis", opener=self.opener(answer("Plants ", "eat light.")))
        self.assertEqual(code, 0)
        self.assertIn("Plants eat light.", out)
        body = self.body()
        self.assertEqual((body["model"], body["prompt"], body["stream"], body["think"]), ("qwen3.8:27b", "EXPLAIN photosynthesis", True, False))
        self.assertTrue(self.requests[0][0].full_url.endswith("/api/generate"))

    def test_the_answer_is_printed(self):
        out = io.StringIO()
        config = M.load_config(Path(self.config))
        self.assertEqual(myassistant.ask(config, "deep_study", "entropy", out=out, opener=self.opener(answer("Heat ", "flows."))), 0)
        self.assertIn("Heat flows.", out.getvalue())
        self.assertEqual(self.body()["prompt"], "DEEP\nentropy")

    def test_describe_image_sends_the_picture(self):
        image = self.tmp / "my picture.png"
        image.write_bytes(b"\x89PNGfake")
        self.call("describe-image", str(image), opener=self.opener(answer("A cat.")))
        body = self.body()
        self.assertEqual(body["prompt"], "DESCRIBE")
        self.assertEqual(base64.b64decode(body["images"][0]), b"\x89PNGfake")

    def test_describe_image_without_a_file_takes_the_newest_screenshot(self):
        folder = self.tmp / "shots"
        folder.mkdir()
        (folder / "old.png").write_bytes(b"old")
        import os, time
        os.utime(folder / "old.png", (time.time() - 100, time.time() - 100))
        (folder / "new.png").write_bytes(b"new")
        (folder / "notes.txt").write_text("x")
        self.config = str(self.write_config(support.good_config([self.tmp / "Applications"], screenshot={"directory": str(folder)})))
        (Path(self.config).parent / "prompts.json").write_text(json.dumps({"describe_image": "D"}))
        self.call("describe-image", opener=self.opener(answer("ok")))
        self.assertEqual(base64.b64decode(self.body()["images"][0]), b"new")

    def test_problems_are_one_line(self):
        code, _, err = self.call("describe-image", "/no/such.png", opener=self.opener())
        self.assertEqual(code, 1)
        self.assertIn("no image at", err)
        (self.tmp / "x.heic").write_bytes(b"x")
        self.assertIn("sips", self.call("describe-image", str(self.tmp / "x.heic"), opener=self.opener())[2])
        missing = urllib.error.HTTPError("u", 404, "nf", {}, io.BytesIO(b'{"error":"model not found"}'))
        code, _, err = self.call("explain", "x", opener=self.opener(missing))
        self.assertIn("ollama pull qwen3.8:27b", err)
        code, _, err = self.call("explain", "x", opener=self.opener(Response([{"error": "out of memory"}])))
        self.assertIn("out of memory", err)

    def test_ollama_not_running_is_started_then_retried(self):
        down = urllib.error.URLError(ConnectionRefusedError(61, "refused"))
        code, out, _ = self.call("explain", "x", opener=self.opener(down, Response([]), answer("hi")))  # 1st try, health check, retry
        self.assertEqual(code, 0)
        self.assertEqual(self.spawned[0][0], ["ollama", "serve"])

    def test_autostart_can_be_off(self):
        cfg = support.good_config([self.tmp / "Applications"], ollama={"autostart": False})
        path = self.write_config(cfg)
        (path.parent / "prompts.json").write_text(json.dumps({"explain": "E {topic}"}))
        self.config = str(path)
        down = urllib.error.URLError(ConnectionRefusedError(61, "refused"))
        code, _, err = self.call("explain", "x", opener=self.opener(down))
        self.assertEqual(code, 1)
        self.assertIn("not running", err)
        self.assertEqual(self.spawned, [])

    def test_launcher_rows_open_a_terminal_with_the_cli(self):
        for typed, ident, expect in (("explain black holes", "ai:explain", ["explain", "--", "black holes"]),
                                     ("deep_study entropy", "ai:deep_study", ["deep-study", "--", "entropy"])):
            row = json.loads(self.call("search", typed, "--json")[1])["results"][0]
            self.assertEqual((row["id"], row["action"]), (ident, "execute_terminal"))
            self.assertIn(" ".join(expect).replace("black holes", "'black holes'"), row["target"])
            self.assertTrue(row["target"].startswith("/bin/bash ") and "/cli/ml " in row["target"])
        for typed in ("explain ", "deep-study "):
            self.assertTrue(json.loads(self.call("search", typed, "--json")[1])["results"][0]["id"].startswith("info:"))

    def test_launcher_describe_image_row(self):
        row = json.loads(self.call("search", "describe_image ~/Pictures/a b.png", "--json")[1])["results"][0]
        self.assertEqual(row["id"], "ai:describe_image")
        self.assertIn("describe-image", row["target"])

    def test_enter_runs_it_in_a_terminal(self):
        runner = support.FakeRunner()
        code, out, _ = self.call("run", "--id", "ai:explain", "--text", "explain black holes", "--yes", "--json", runner=runner)
        self.assertEqual(code, 0)
        self.assertTrue(any("ml explain -- 'black holes'" in " ".join(map(str, c)) for c in [*runner.calls, *[sp[0] for sp in self.spawned]]), (runner.calls, self.spawned))

    def test_settings_are_validated(self):
        for bad in ({"host": "localhost:11434"}, {"model": " "}, {"think": "yes"}, {"timeout_seconds": 1}):
            with self.assertRaises(ConfigError):
                parse_config(support.good_config(["/tmp"], ollama=bad), Path("x.json"))
        c = parse_config(support.good_config(["/tmp"], ollama={"think": None}), Path("/etc/conf/x.json"))
        self.assertIsNone(c.ollama_think)
        self.assertEqual(c.ollama_prompts, Path("/etc/conf/prompts.json"))


if __name__ == "__main__":
    unittest.main()


class FindImage(CliCase):
    """ml find-image FOLDER TOPIC"""

    def opener(self, *responses):
        queue = list(responses)

        def open_(request, timeout=0):
            item = queue.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        return open_

    def setUp(self):
        super().setUp()
        cfg = support.good_config([self.tmp / "Applications"], ollama={"cache_file": str(self.tmp / "cache.json")})
        path = self.write_config(cfg)
        prompts = json.loads((Path(__file__).resolve().parent.parent / "conf" / "prompts.json").read_text())
        (path.parent / "prompts.json").write_text(json.dumps(prompts))
        self.config = str(path)
        self.pics = self.tmp / "static" / "education"
        (self.pics / "images").mkdir(parents=True)
        (self.pics / "images" / "jesusChrist.jpg").write_bytes(b"a")
        (self.pics / "images" / "volcano.png").write_bytes(b"b")
        (self.pics / "deep" / "er").mkdir(parents=True)
        (self.pics / "deep" / "er" / "church_window.webp").write_bytes(b"c")
        (self.pics / ".hidden").mkdir()
        (self.pics / ".hidden" / "secret.png").write_bytes(b"d")
        (self.pics / "notes.txt").write_text("x")
        self.captions = 0

    def fake(self):
        """A model that describes pictures and, asked about a topic, picks the numbers of religious ones."""
        def open_(request, timeout=0):
            body = json.loads(request.data)
            if body.get("images"):
                self.captions += 1
                text = "A volcano erupting." if base64.b64decode(body["images"][0]) == b"b" else "A holy scene with a halo."
                return answer(text)
            lines = [l for l in body["prompt"].splitlines() if "::" in l]
            key = "holy" if "Topic: religious" in body["prompt"] else "volcano"
            picked = [l.split(".")[0] for l in lines if key in l]
            return answer(json.dumps([int(n) for n in picked]))
        return open_

    def test_finds_by_content_and_prints_paths(self):
        code, out, err = self.call("find-image", str(self.pics), "religious", opener=self.fake())
        self.assertEqual(code, 0)
        self.assertEqual(sorted(out.split()), sorted([str(self.pics / "images" / "jesusChrist.jpg"), str(self.pics / "deep" / "er" / "church_window.webp")]))
        self.assertEqual(self.captions, 3)  # the hidden folder and the txt are not looked at
        self.assertIn("3 to look at", err)

    def test_second_search_uses_the_cache(self):
        self.call("find_image", str(self.pics), "religious", opener=self.fake())
        before = self.captions
        code, out, _ = self.call("find-image", str(self.pics), "volcanoes", opener=self.fake())
        self.assertEqual(self.captions, before)  # no new picture looked at
        self.assertEqual((code, out.split()), (0, [str(self.pics / "images" / "volcano.png")]))  # a new topic, same cached descriptions
        self.call("find-image", str(self.pics), "religious", "--refresh", opener=self.fake())
        self.assertEqual(self.captions, before + 3)

    def test_changed_picture_is_looked_at_again(self):
        self.call("find-image", str(self.pics), "religious", opener=self.fake())
        before = self.captions
        import os
        target = self.pics / "images" / "volcano.png"
        target.write_bytes(b"bb")
        os.utime(target, (1, 1))
        self.call("find-image", str(self.pics), "religious", opener=self.fake())
        self.assertEqual(self.captions, before + 1)

    def test_limit_goes_on_next_time(self):
        self.call("find-image", str(self.pics), "religious", "--limit", "2", opener=self.fake())
        self.assertEqual(self.captions, 2)
        self.call("find-image", str(self.pics), "religious", "--limit", "2", opener=self.fake())
        self.assertEqual(self.captions, 3)

    def test_names_only_needs_no_model(self):
        code, out, _ = self.call("find-image", str(self.pics), "jesus", "christ", "--names-only", "--json", opener=self.opener())
        self.assertEqual(json.loads(out), [str(self.pics / "images" / "jesusChrist.jpg")])
        code, out, _ = self.call("find-image", str(self.pics), "church", "--names-only", opener=self.opener())
        self.assertIn("church_window.webp", out)

    def test_problems(self):
        self.assertIn("not a folder", self.call("find-image", "/no/such/dir", "x", opener=self.opener())[2])
        (Path(self.config).parent / "prompts.json").write_text(json.dumps({"explain": "E {topic}"}))
        self.assertIn("caption_image", self.call("find-image", str(self.pics), "x", opener=self.opener())[2])

    def test_number_parsing(self):
        self.assertEqual(myassistant.parse_numbers("Sure: [3, 1, 9, 2]", 5), [1, 2, 3])
        self.assertEqual(myassistant.parse_numbers("1 and 4", 5), [1, 4])
        self.assertEqual(myassistant.parse_numbers("[]", 5), [])
        self.assertEqual(myassistant.words_of("jesusChrist_01.jpg"), ["jesus", "christ", "01", "jpg"])
