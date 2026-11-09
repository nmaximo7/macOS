"""mysearx (settings, query, parsing, HTTP, lifecycle, CLI), content_searx, the "searx" step,
the research-aware rewrite, searx.sh, and the self-containment of mysearx / myollama."""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import content_creation as CC
import content_expand as E
import content_searx as CS
import mymessages
import mysearx as S

ROOT = Path(__file__).resolve().parent.parent
# searx.sh lives next to the toolkit in the zip, and in ~/macOS/scripts/ in your dotfiles repo.
SCRIPT = next((p for p in (ROOT / "searx.sh", ROOT.parent / "scripts" / "searx.sh") if p.is_file()), ROOT / "searx.sh")


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class FakeSearx:
    """A tiny HTTP server that behaves like SearXNG: /healthz, /search?format=json."""

    def __init__(self, mode="ok", results=None):
        self.mode, self.requests = mode, []
        self.results = results if results is not None else [
            {"title": "Faraday's law", "url": "https://en.wikipedia.org/wiki/Faraday%27s_law", "content": "<b>Law</b> of induction &amp; flux", "engine": "wikipedia"},
            {"title": "Faraday again", "url": "https://www.en.wikipedia.org/wiki/Faraday%27s_law/?utm_source=x", "content": "dup"},
            {"title": "Evil", "url": "javascript:alert(1)", "content": "x"},
            {"title": "Mine", "url": "https://justtothepoint.com/page", "content": "my site"},
            {"title": "Khan", "url": "https://khanacademy.org/faraday", "content": "lesson", "publishedDate": "2024-05-01T00:00:00"},
        ]
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                owner.requests.append(self.path)
                if self.path.startswith("/healthz") or self.path == "/":
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"OK")
                    return
                if owner.mode in ("403", "429"):
                    self.send_response(int(owner.mode))
                    self.end_headers()
                    return
                if owner.mode == "html":
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"<html>not json</html>")
                    return
                body = json.dumps({"results": owner.results, "suggestions": ["faraday law"], "answers": [{"answer": "42"}],
                                   "unresponsive_engines": [["google", "timeout"]]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class WithFake(unittest.TestCase):
    mode = "ok"

    def setUp(self):
        self.fake = FakeSearx(self.mode)
        self.addCleanup(self.fake.close)
        self.cfg = S.SearxConfig(url=self.fake.url, timeout=5, exclude=("justtothepoint.com",))


class Settings(unittest.TestCase):
    def test_dotenv_parser(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(Path(tmp) / ".env", '# c\nA=1\nexport B="two words"\nC=x # note\nD=\'q\'\nbad line\n1X=no\n')
            self.assertEqual(S._dotenv_values(path), {"A": "1", "B": "two words", "C": "x", "D": "q"})
        self.assertEqual(S._dotenv_values(Path("/nonexistent/.env")), {})

    def test_defaults(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(S, "_dotenv_values", return_value={}):
            cfg = S.load_config()
        self.assertEqual((cfg.url, cfg.limit, cfg.categories, cfg.autostart, cfg.autostop), (S.DEFAULT_URL, 8, "general", True, True))
        self.assertEqual(cfg.port, 8080)
        self.assertTrue(cfg.is_local)

    def test_environment_wins_over_dotenv(self):
        with mock.patch.dict(os.environ, {"SEARX_RESULTS": "3"}, clear=True), \
                mock.patch.object(S, "_dotenv_values", return_value={"SEARX_RESULTS": "9", "SEARX_LANGUAGE": "es"}):
            cfg = S.load_config()
        self.assertEqual((cfg.limit, cfg.language), (3, "es"))

    def test_values_are_normalised(self):
        env = {"SEARX_URL": "localhost:9090/", "SEARX_EXCLUDE": "A.com, .b.org", "SEARX_AUTOSTART": "no", "SEARX_QUIT_DOCKER": "0"}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(S, "_dotenv_values", return_value={}):
            cfg = S.load_config()
        self.assertEqual(cfg.url, "http://localhost:9090")
        self.assertEqual(cfg.port, 9090)
        self.assertEqual(cfg.exclude, ("a.com", "b.org"))
        self.assertFalse(cfg.autostart)
        self.assertFalse(cfg.quit_docker)

    def test_always_modes_from_the_environment(self):
        for raw, expected in (("always", (True, True)), ("ALWAYS", (True, True)), ("1", (True, False)), ("0", (False, False)), ("", (True, False)), ("no", (False, False))):
            env = {"SEARX_AUTOSTOP": raw, "SEARX_QUIT_DOCKER": raw}
            with self.subTest(raw=raw), mock.patch.dict(os.environ, env, clear=True), mock.patch.object(S, "_dotenv_values", return_value={}):
                cfg = S.load_config()
            self.assertEqual((cfg.autostop, cfg.stop_always), expected)
            self.assertEqual((cfg.quit_docker, cfg.quit_docker_always), expected)

    def test_the_users_own_env_values(self):
        env = {"SEARX_RESULTS": "8", "SEARX_LANGUAGE": "en", "SEARX_CATEGORIES": "general", "SEARX_ENGINES": "duckduckgo",
               "SEARX_TIMEOUT": "30", "SEARX_AUTOSTART": "1", "SEARX_AUTOSTOP": "always", "SEARX_QUIT_DOCKER": "always",
               "SEARX_SCRIPT": "~/macOS/scripts/searx.sh", "SEARX_EXCLUDE": "justtothepoint.com"}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(S, "_dotenv_values", return_value={}):
            cfg = S.load_config()
        self.assertEqual((cfg.limit, cfg.language, cfg.categories, cfg.engines, cfg.timeout), (8, "en", "general", "duckduckgo", 30.0))
        self.assertTrue(cfg.autostart and cfg.stop_always and cfg.quit_docker_always)
        self.assertEqual(cfg.script, Path.home() / "macOS" / "scripts" / "searx.sh")  # ~ is expanded
        self.assertEqual(cfg.exclude, ("justtothepoint.com",))

    def test_bad_values_name_the_variable(self):
        for name, value in (("SEARX_RESULTS", "many"), ("SEARX_RESULTS", "0"), ("SEARX_TIME_RANGE", "decade"), ("SEARX_TIMEOUT", "x"), ("SEARX_URL", "ftp://x")):
            with self.subTest(name=name, value=value), mock.patch.dict(os.environ, {name: value}, clear=True), \
                    mock.patch.object(S, "_dotenv_values", return_value={}):
                with self.assertRaises(S.SearxError) as ctx:
                    S.load_config()
                self.assertIn(name, str(ctx.exception))

    def test_remote_instance_is_not_local(self):
        self.assertFalse(S.SearxConfig(url="https://searx.example.org").is_local)


class BuildQuery(unittest.TestCase):
    def test_title_is_the_query(self):
        self.assertEqual(S.build_query("Maxwell-Faraday equation and induction"), "Maxwell-Faraday equation and induction")

    def test_markup_is_removed(self):
        self.assertEqual(S.build_query("The `foo` *bar* [baz]"), "The foo bar baz")

    def test_short_title_gets_two_tags(self):
        self.assertEqual(S.build_query("Fourier", ["signals", "maths", "extra"]), "Fourier signals maths")

    def test_tag_already_in_title_is_not_repeated(self):
        self.assertEqual(S.build_query("Fourier", ["fourier", "maths"]), "Fourier maths")

    def test_long_title_keeps_all_its_words_up_to_the_limit(self):
        title = " ".join(f"w{i}" for i in range(30))
        self.assertEqual(len(S.build_query(title).split()), 12)

    def test_no_title_uses_the_description(self):
        self.assertEqual(S.build_query("", description="A very nice article about Rust ownership rules and more words here now"),
                         "A very nice article about Rust ownership rules")

    def test_nothing_at_all(self):
        self.assertEqual(S.build_query("", [], ""), "")

    def test_html_entities_and_tags(self):
        self.assertEqual(S.build_query("Tom &amp; <b>Jerry</b> cartoons"), "Tom & Jerry cartoons")


class Parsing(unittest.TestCase):
    def test_filters_and_limits(self):
        fake = FakeSearx()
        self.addCleanup(fake.close)
        results, total = S.parse_results({"results": fake.results}, limit=10, exclude=("justtothepoint.com",))
        titles = [r.title for r in results]
        self.assertEqual(titles, ["Faraday's law", "Khan"])  # duplicate, javascript: and own site are gone
        self.assertEqual(total, 5)
        self.assertEqual(results[0].snippet, "Law of induction & flux")  # tags removed, entities decoded
        self.assertEqual(results[1].published, "2024-05-01")
        self.assertEqual(results[1].domain, "khanacademy.org")
        self.assertEqual(len(S.parse_results({"results": fake.results}, limit=1)[0]), 1)

    def test_subdomains_of_an_excluded_domain_are_excluded(self):
        data = {"results": [{"title": "t", "url": "https://blog.justtothepoint.com/x"}, {"title": "u", "url": "https://notjusttothepoint.com/x"}]}
        self.assertEqual([r.title for r in S.parse_results(data, 5, ("justtothepoint.com",))[0]], ["u"])

    def test_only_http_and_https_links_are_kept(self):
        data = {"results": [{"title": t, "url": u} for t, u in
                            (("ftp", "ftp://a.org/x"), ("file", "file://host/etc/passwd"), ("js", "javascript:alert(1)"),
                             ("ok", "http://a.org/x"), ("ok2", "https://b.org/y"))]}
        self.assertEqual([r.title for r in S.parse_results(data, 10)[0]], ["ok", "ok2"])

    def test_garbage_does_not_crash(self):
        for data in (None, [], {"results": "x"}, {"results": [1, None, {"title": "no url"}, {"url": "https://a.org"}]}):
            self.assertEqual(S.parse_results(data, 5)[0], [])

    def test_long_snippet_is_cut(self):
        out = S.parse_results({"results": [{"title": "t", "url": "https://a.org", "content": "w " * 1000}]}, 5)[0][0]
        self.assertLessEqual(len(out.snippet), S.MAX_SNIPPET_CHARS)
        self.assertTrue(out.snippet.endswith("…"))


class Searching(WithFake):
    def test_search(self):
        response = S.search("faraday law", config=self.cfg)
        self.assertEqual([r.title for r in response.results], ["Faraday's law", "Khan"])
        self.assertEqual(response.suggestions, ["faraday law"])
        self.assertEqual(response.answers, ["42"])
        self.assertEqual(response.unresponsive, ["google: timeout"])
        self.assertIn("format=json", self.fake.requests[-1])
        self.assertIn("q=faraday+law", self.fake.requests[-1])

    def test_options_reach_the_server(self):
        S.search("x", language="es", engines="wikipedia", time_range="year", categories="it", config=self.cfg)
        sent = self.fake.requests[-1]
        for part in ("language=es", "engines=wikipedia", "time_range=year", "categories=it"):
            self.assertIn(part, sent)

    def test_bad_arguments(self):
        for kwargs in ({"query": ""}, {"query": "   "}, {"query": "x", "limit": 0}, {"query": "x", "limit": 99}, {"query": "x", "time_range": "decade"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                S.search(config=self.cfg, **kwargs)

    def test_limit(self):
        self.assertEqual(len(S.search("x", limit=1, config=self.cfg).results), 1)

    def test_nothing_listening(self):
        dead = S.SearxConfig(url="http://127.0.0.1:1", timeout=2)
        with self.assertRaises(S.SearxNotRunning) as ctx:
            S.search("x", config=dead)
        self.assertIn("searx.sh start", str(ctx.exception))

    def test_is_up(self):
        self.assertTrue(S.is_up(self.cfg))
        self.assertFalse(S.is_up(S.SearxConfig(url="http://127.0.0.1:1"), timeout=1))


class Refused(WithFake):
    mode = "403"

    def test_403_explains_the_json_setting(self):
        with self.assertRaises(S.SearxError) as ctx:
            S.search("x", config=self.cfg)
        message = str(ctx.exception)
        self.assertIn("403", message)
        self.assertIn("json", message)
        self.assertNotIsInstance(ctx.exception, S.SearxNotRunning)


class RateLimited(WithFake):
    mode = "429"

    def test_429_explains_the_limiter(self):
        with self.assertRaises(S.SearxError) as ctx:
            S.search("x", config=self.cfg)
        self.assertIn("limiter", str(ctx.exception))


class NotJson(WithFake):
    mode = "html"

    def test_html_answer(self):
        with self.assertRaises(S.SearxError) as ctx:
            S.search("x", config=self.cfg)
        self.assertIn("JSON", str(ctx.exception))


class Presenting(unittest.TestCase):
    def response(self):
        return S.SearxResponse("q", [S.SearxResult("T1", "https://a.org/x", "snippet one", published="2024-01-02"),
                                      S.SearxResult("T2", "https://www.b.org/y")])

    def test_format_plain_and_markdown(self):
        plain = S.format_results(self.response())
        self.assertIn("1. T1\n   https://a.org/x\n   snippet one", plain)
        self.assertIn("2. T2\n   https://www.b.org/y", plain)
        self.assertIn("1. [T1](https://a.org/x) - snippet one", S.format_results(self.response(), markdown=True))
        self.assertEqual(S.format_results(S.SearxResponse("zzz")), "No results for 'zzz'.")

    def test_context_has_domain_date_and_url(self):
        text = S.as_context(self.response())
        self.assertIn("[1] T1 (a.org, 2024-01-02)", text)
        self.assertIn("[2] T2 (b.org)", text)  # www. removed
        self.assertIn("https://a.org/x", text)

    def test_context_is_cut_on_a_result_boundary(self):
        many = S.SearxResponse("q", [S.SearxResult(f"Title {i}", f"https://a.org/{i}", "s" * 100) for i in range(50)])
        text = S.as_context(many, max_chars=600)
        self.assertLessEqual(len(text), 600)
        self.assertTrue(text.rstrip().endswith(tuple(f"https://a.org/{i}" for i in range(50))))
        self.assertEqual(S.as_context(S.SearxResponse("q")), "")


class Lifecycle(unittest.TestCase):
    def cfg(self, **kw):
        return S.SearxConfig(url="http://127.0.0.1:8080", **kw)

    def test_already_running_is_left_alone(self):
        with mock.patch.object(S, "is_up", return_value=True), mock.patch.object(S, "_run_script") as run:
            with S.running(self.cfg()) as started:
                self.assertFalse(started)
        run.assert_not_called()

    def test_started_here_is_stopped_here(self):
        calls = []
        with mock.patch.object(S, "is_up", side_effect=[False, True]), \
                mock.patch.object(S, "_run_script", side_effect=lambda args, cfg, t: calls.append(list(args)) or ""):
            with S.running(self.cfg()) as started:
                self.assertTrue(started)
        self.assertEqual(calls, [["start"], ["stop"]])

    def test_stopped_even_when_the_block_fails(self):
        calls = []
        with mock.patch.object(S, "is_up", side_effect=[False, True]), \
                mock.patch.object(S, "_run_script", side_effect=lambda args, cfg, t: calls.append(list(args)) or ""):
            with self.assertRaises(KeyError), S.running(self.cfg()):
                raise KeyError("boom")
        self.assertEqual(calls[-1], ["stop"])

    def test_autostop_off_leaves_it_running(self):
        calls = []
        with mock.patch.object(S, "is_up", side_effect=[False, True]), \
                mock.patch.object(S, "_run_script", side_effect=lambda args, cfg, t: calls.append(list(args)) or ""):
            with S.running(self.cfg(autostop=False)):
                pass
        self.assertEqual(calls, [["start"]])

    def test_keep_docker_flag(self):
        with mock.patch.object(S, "_run_script") as run:
            S.stop(self.cfg(quit_docker=False))
        self.assertEqual(run.call_args.args[0], ["stop", "--keep-docker"])
        with mock.patch.object(S, "_run_script") as run:
            S.stop(self.cfg())
        self.assertEqual(run.call_args.args[0], ["stop"])

    def test_always_stops_even_what_was_already_running(self):
        calls = []
        with mock.patch.object(S, "is_up", return_value=True), \
                mock.patch.object(S, "_run_script", side_effect=lambda args, cfg, t: calls.append(list(args)) or ""):
            with S.running(self.cfg(stop_always=True)) as started:
                self.assertFalse(started)
        self.assertEqual(calls, [["stop"]])

    def test_keep_overrides_always(self):
        with mock.patch.object(S, "is_up", return_value=True), mock.patch.object(S, "_run_script") as run:
            with S.running(self.cfg(stop_always=True), autostop=False):
                pass
        run.assert_not_called()

    def test_autostop_zero_never_stops(self):
        with mock.patch.object(S, "is_up", side_effect=[False, True]), mock.patch.object(S, "_run_script") as run:
            with S.running(self.cfg(autostop=False, stop_always=True)):
                pass
        self.assertEqual([c.args[0] for c in run.call_args_list], [["start"]])

    def test_quit_docker_always_passes_the_forcing_flag(self):
        with mock.patch.object(S, "_run_script") as run:
            S.stop(self.cfg(quit_docker_always=True))
        self.assertEqual(run.call_args.args[0], ["stop", "--quit-docker"])
        with mock.patch.object(S, "_run_script") as run:
            S.stop(self.cfg(quit_docker=False, quit_docker_always=True))  # "never" wins
        self.assertEqual(run.call_args.args[0], ["stop", "--keep-docker"])

    def test_autostart_off_is_an_error_when_down(self):
        with mock.patch.object(S, "is_up", return_value=False):
            with self.assertRaises(S.SearxNotRunning) as ctx:
                S.ensure_running(self.cfg(autostart=False))
        self.assertIn("SEARX_AUTOSTART", str(ctx.exception))

    def test_remote_instance_cannot_be_started(self):
        with mock.patch.object(S, "is_up", return_value=False):
            with self.assertRaises(S.SearxNotRunning):
                S.start(S.SearxConfig(url="https://searx.example.org"))

    def test_start_that_does_not_come_up_is_an_error(self):
        with mock.patch.object(S, "is_up", return_value=False), mock.patch.object(S, "_run_script", return_value=""):
            with self.assertRaises(S.SearxError):
                S.start(self.cfg())

    def test_port_is_passed_to_the_script(self):
        done = SimpleNamespace(returncode=0, stdout="ok", stderr="")
        with tempfile.TemporaryDirectory() as tmp:
            script = write(Path(tmp) / "searx.sh", "#!/bin/bash\n")
            with mock.patch.object(S, "find_script", return_value=script), mock.patch("subprocess.run", return_value=done) as run:
                S._run_script(["start"], S.SearxConfig(url="http://127.0.0.1:9191"), 5)
        self.assertEqual(run.call_args.kwargs["env"]["SEARX_PORT"], "9191")
        self.assertEqual(run.call_args.args[0][-1], "start")

    def test_script_failure_shows_its_last_lines(self):
        done = SimpleNamespace(returncode=1, stdout="", stderr="line1\nDocker did not start")
        with tempfile.TemporaryDirectory() as tmp:
            script = write(Path(tmp) / "searx.sh", "")
            with mock.patch.object(S, "find_script", return_value=script), mock.patch("subprocess.run", return_value=done):
                with self.assertRaises(S.SearxError) as ctx:
                    S._run_script(["start"], self.cfg(), 5)
        self.assertIn("Docker did not start", str(ctx.exception))

    def test_missing_script(self):
        with mock.patch.object(S, "find_script", return_value=None):
            with self.assertRaises(S.SearxError) as ctx:
                S._run_script(["start"], self.cfg(), 5)
        self.assertIn("searx.sh not found", str(ctx.exception))

    def test_find_script_prefers_the_setting(self):
        with tempfile.TemporaryDirectory() as tmp:
            mine = write(Path(tmp) / "mine.sh", "")
            self.assertEqual(S.find_script(self.cfg(script=mine)), mine)


class SearxCli(WithFake):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(S, "load_config", return_value=self.cfg), mock.patch.object(S, "is_up", return_value=True), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = S.cli(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_text(self):
        code, out, _ = self.run_cli("faraday", "law")
        self.assertEqual(code, 0)
        self.assertIn("1. Faraday's law", out)

    def test_json(self):
        code, out, _ = self.run_cli("faraday", "--json", "--limit", "1")
        data = json.loads(out)
        self.assertEqual((code, len(data["results"]), data["query"]), (0, 1, "faraday"))

    def test_markdown(self):
        self.assertIn("[Faraday's law](https://en.wikipedia.org/wiki/Faraday%27s_law)", self.run_cli("x", "--markdown")[1])

    def test_no_query_is_a_usage_error(self):
        self.assertEqual(self.run_cli()[0], 2)

    def test_errors_exit_1(self):
        with mock.patch.object(S, "search", side_effect=S.SearxError("nope")):
            code, _, err = self.run_cli("x")
        self.assertEqual(code, 1)
        self.assertIn("error: nope", err)

    def test_bad_limit_is_a_usage_error(self):
        self.assertEqual(self.run_cli("x", "--limit", "500")[0], 2)

    def test_status(self):
        self.assertEqual(self.run_cli("--status")[0], 0)


# --------------------------------------------------------------------------- #
# content_searx                                                               #
# --------------------------------------------------------------------------- #


class PageFields(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def page(self, text, name="faraday.md"):
        return write(self.dir / name, text)

    def test_title_and_lists(self):
        page = self.page('---\ntitle: "Maxwell: Faraday"\nkeywords: induction, flux\ntags:\n  - emf\n  - "lenz law"\ncategories: [Physics]\ndescription: Short.\n---\n# Heading\n')
        self.assertEqual(CS.page_fields(page), ("Maxwell: Faraday", ["induction", "flux", "emf", "lenz law", "Physics"], "Short."))

    def test_title_from_first_heading(self):
        self.assertEqual(CS.page_fields(self.page("---\nweight: 3\n---\n\nintro\n\n## The Law\n"))[0], "The Law")

    def test_title_from_file_name(self):
        self.assertEqual(CS.page_fields(self.page("just text", "my-page_name.md"))[0], "my page name")
        self.assertEqual(CS.page_fields(self.page("text", "topic/index.md"))[0], "topic")

    def test_crlf(self):
        page = self.dir / "c.md"
        page.write_bytes(b"---\r\ntitle: Crlf title\r\n---\r\nBody\r\n")
        self.assertEqual(CS.page_fields(page)[0], "Crlf title")


class ResearchPage(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.page = write(Path(self._tmp.name) / "faraday.md", "---\ntitle: Faraday law of induction\nkeywords: emf\n---\nBody text.\n")
        self.response = S.SearxResponse("Faraday law of induction", [S.SearxResult("T", "https://a.org/x", "snip")])
        self.cfg = S.SearxConfig(url="http://127.0.0.1:8080")

    def run_research(self, **kw):
        @contextlib.contextmanager
        def fake_running(cfg, autostart=None, autostop=None):
            self.autostop_seen = autostop
            yield False

        with mock.patch.object(S, "load_config", return_value=self.cfg), mock.patch.object(S, "is_up", return_value=True), \
                mock.patch.object(S, "running", fake_running), \
                mock.patch.object(S, "search", return_value=self.response) as search, \
                contextlib.redirect_stdout(io.StringIO()):
            kw.setdefault("deep", False)  # these tests are about the single plain search
            research = CS.research_page(self.page, **kw)
        return research, search

    def test_the_title_is_searched(self):
        research, search = self.run_research()
        self.assertEqual(search.call_args.args[0], "Faraday law of induction")
        self.assertEqual(research.query, "Faraday law of induction")
        self.assertEqual(research.urls, ("https://a.org/x",))
        self.assertIn("[1] T (a.org)", research.text)
        self.assertEqual(research.count, 1)

    def test_query_override_and_options(self):
        research, search = self.run_research(query="my own query", limit=3, autostop=False)
        self.assertEqual(search.call_args.args[0], "my own query")
        self.assertEqual(search.call_args.kwargs["limit"], 3)
        self.assertIs(self.autostop_seen, False)

    def test_page_without_any_usable_title(self):
        empty = write(Path(self._tmp.name) / "e.md", "---\n---\n")
        # the file name is the last resort, so there is always a query
        with mock.patch.object(S, "load_config", return_value=self.cfg), mock.patch.object(S, "is_up", return_value=True), \
                mock.patch.object(S, "search", return_value=self.response) as search, \
                mock.patch.object(S, "running", lambda *a, **k: contextlib.nullcontext(False)), \
                contextlib.redirect_stdout(io.StringIO()):
            CS.research_page(empty, deep=False)
        self.assertEqual(search.call_args.args[0], "e")


class SearxStep(unittest.TestCase):
    def setUp(self):
        self.page = Path("/site/content/x.md")
        CC._research.clear()
        self.addCleanup(CC._research.clear)
        self.addCleanup(CC._searx_options.update, CC._SEARX_DEFAULTS)

    def research(self, n=2):
        response = S.SearxResponse("q", [S.SearxResult(f"T{i}", f"https://a.org/{i}") for i in range(n)])
        return CS.Research("q", response, "context text", tuple(r.url for r in response.results))

    def test_success_keeps_the_research_for_the_rewrite(self):
        with mock.patch("content_searx.research_page", return_value=self.research()):
            status, detail = CC._step_searx(self.page, True)
        self.assertEqual(status, CC.PROPOSAL)
        self.assertIn("2 result(s)", detail)
        self.assertEqual(CC._research[str(self.page)].text, "context text")

    def test_no_results_is_unchecked_and_keeps_nothing(self):
        with mock.patch("content_searx.research_page", return_value=self.research(0)):
            status, detail = CC._step_searx(self.page, True)
        self.assertEqual(status, CC.UNCHECKED)
        self.assertNotIn(str(self.page), CC._research)

    def test_no_results_names_the_engine_that_did_not_answer(self):
        research = self.research(0)
        research.response.unresponsive = ["duckduckgo: CAPTCHA"]
        with mock.patch("content_searx.research_page", return_value=research):
            status, detail = CC._step_searx(self.page, True)
        self.assertEqual(status, CC.UNCHECKED)
        self.assertIn("duckduckgo: CAPTCHA", detail)

    def test_failure_is_unchecked_not_a_crash(self):
        with mock.patch("content_searx.research_page", side_effect=S.SearxNotRunning("nothing answers")), \
                contextlib.redirect_stdout(io.StringIO()):
            status, detail = CC._step_searx(self.page, True)
        self.assertEqual((status, detail), (CC.UNCHECKED, "nothing answers"))

    def test_a_failed_search_does_not_reuse_an_old_result(self):
        CC._research[str(self.page)] = self.research()
        with mock.patch("content_searx.research_page", side_effect=S.SearxError("down")), contextlib.redirect_stdout(io.StringIO()):
            CC._step_searx(self.page, True)
        self.assertNotIn(str(self.page), CC._research)

    def test_options_reach_research_page(self):
        CC._searx_options.update(query="q2", limit=4, autostop=False)
        with mock.patch("content_searx.research_page", return_value=self.research()) as rp:
            CC._step_searx(self.page, True)
        self.assertEqual(rp.call_args.kwargs, {"query": "q2", "limit": 4, "autostop": False})

    def test_expand_receives_the_research(self):
        CC._research[str(self.page)] = self.research()
        result = SimpleNamespace(serious=False, words_before=1, words_after=2, saved_to=None, warnings=[])
        with mock.patch("content_expand.expand_article", return_value=result) as expand:
            CC._step_expand(self.page, True)
        self.assertEqual(expand.call_args.kwargs["research"], "context text")
        self.assertEqual(expand.call_args.kwargs["research_urls"], ("https://a.org/0", "https://a.org/1"))

    def test_expand_without_research_is_unchanged(self):
        result = SimpleNamespace(serious=False, words_before=1, words_after=2, saved_to=None, warnings=[])
        with mock.patch("content_expand.expand_article", return_value=result) as expand:
            CC._step_expand(self.page, True)
        self.assertNotIn("research", expand.call_args.kwargs)

    def test_main_forgets_the_previous_run(self):
        CC._research["old"] = self.research()
        with mock.patch.object(CC, "find_page", return_value=(None, [])), contextlib.redirect_stdout(io.StringIO()):
            CC.main("nope.md", searx_options={"query": "zzz"})
        self.assertEqual(CC._research, {})
        self.assertEqual(CC._searx_options["query"], "zzz")
        CC.main("nope.md")  # next call starts from the defaults
        self.assertIsNone(CC._searx_options["query"])

    def test_cli_flags(self):
        with mock.patch.object(CC, "main", return_value=0) as main:
            CC.cli(["p.md", "--search", "my q", "--search-results", "5", "--keep-searx"])
        self.assertEqual(main.call_args.kwargs["searx_options"], {"query": "my q", "limit": 5, "autostop": False})
        with mock.patch.object(CC, "main", return_value=0) as main:
            CC.cli(["p.md"])
        self.assertEqual(main.call_args.kwargs["searx_options"], {"query": None, "limit": None, "autostop": None})

    def test_skip_and_only_know_the_step(self):
        self.assertIn("searx", CC.STEP_KEYS)
        self.assertLess(CC.STEP_KEYS.index("searx"), CC.STEP_KEYS.index("expand"))


# --------------------------------------------------------------------------- #
# The rewrite that receives research                                          #
# --------------------------------------------------------------------------- #

ARTICLE = "# Faraday\n\nFaraday's law links flux and field. See [notes](https://example.org/n).\n\n## The law\n\nIt is an equation.\n"


class ExpandWithResearch(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name).resolve()
        self.page = write(root / "site" / "content" / "f.md", "---\ntitle: F\n---\n" + ARTICLE)
        settings = SimpleNamespace(expand_output_dir=root / "out", hugo_root=root / "site", expand_provider="openrouter",
                                   model_query="m", openrouter_model="o")
        p = mock.patch.object(E, "get_settings", return_value=settings)
        p.start()
        self.addCleanup(p.stop)
        self.long = ARTICLE + "\n" + "More careful words about the law. " * 40

    def run_expand(self, answer, **kw):
        with mock.patch.object(E, "_ask_openrouter", return_value=(answer, "vendor/m", 1)) as ask, contextlib.redirect_stdout(io.StringIO()):
            result = E.expand_article(self.page, save=False, **kw)
        return result, ask

    def test_without_research_nothing_changes(self):
        _, ask = self.run_expand(self.long)
        self.assertEqual(ask.call_args.kwargs["prompt"], "expand_article")
        self.assertEqual(ask.call_args.args[0], ARTICLE.strip())

    def test_with_research_the_message_has_both_parts_and_the_other_prompt(self):
        _, ask = self.run_expand(self.long, research="[1] T (a.org)\n    https://a.org/x")
        sent = ask.call_args.args[0]
        self.assertTrue(sent.startswith("<article>\n# Faraday"))
        self.assertIn("</article>\n\n<web_research>\n[1] T (a.org)", sent)
        self.assertEqual(ask.call_args.kwargs["prompt"], "expand_article_research")

    def test_research_is_cut(self):
        _, ask = self.run_expand(self.long, research="x" * 50_000)
        self.assertLess(len(ask.call_args.args[0]), len(ARTICLE) + E.MAX_RESEARCH_CHARS + 200)

    def test_blank_research_counts_as_none(self):
        _, ask = self.run_expand(self.long, research="   \n ")
        self.assertEqual(ask.call_args.kwargs["prompt"], "expand_article")

    def test_echoed_tags_never_reach_the_site(self):
        result, _ = self.run_expand("<article>\n" + self.long + "\n</article>", research="r")
        self.assertNotIn("<article>", result.text)
        self.assertNotIn("</article>", result.text)
        self.assertTrue(any("tags the model echoed" in n for n in result.notes))

    def test_links_from_the_search_are_a_note_not_a_warning(self):
        answer = self.long + "\n\n## Further reading\n\n- [Wiki](https://en.wikipedia.org/wiki/Faraday)\n"
        result, _ = self.run_expand(answer, research="r", research_urls=("https://en.wikipedia.org/wiki/Faraday",))
        self.assertFalse(any("NEW link" in w for w in result.warnings), result.warnings)
        self.assertTrue(any("from the web search" in n for n in result.notes))

    def test_an_invented_link_is_still_a_warning_even_with_research(self):
        answer = self.long + "\n\nSee [x](https://invented.example/page)\n"
        result, _ = self.run_expand(answer, research="r", research_urls=("https://en.wikipedia.org/wiki/Faraday",))
        self.assertTrue(any("NEW link" in w and "invented.example" in w for w in result.warnings))

    def test_compare_texts_without_known_urls_is_unchanged(self):
        warnings, _ = E.compare_texts(ARTICLE, ARTICLE + "\n[x](https://new.example/a)\n" + "word " * 100)
        self.assertTrue(any("NEW link" in w for w in warnings))

    def test_the_prompt(self):
        self.assertIn("expand_article_research", mymessages.available_prompts())
        text = mymessages.expand_article_research["content"]
        self.assertTrue(text.startswith(mymessages.expand_article["content"]))  # the six base rules are inherited
        for needle in ("<web_research>", "untrusted", "Further reading", "ONLY the exact URLs"):
            self.assertIn(needle, text)
        self.assertNotIn("_RESEARCH_RULES", mymessages.available_prompts())


# --------------------------------------------------------------------------- #
# Self-containment: the two modules run with NOTHING else of the toolkit      #
# --------------------------------------------------------------------------- #

BLOCK = "for n in ('rich','colorama','dotenv','ollama','requests','keyring','util','myconfig','content_urls','openrouter'): sys.modules[n] = None\n"


class SelfContained(unittest.TestCase):
    def run_py(self, code, cwd):
        return subprocess.run([sys.executable, "-I", "-c", "import sys\n" + BLOCK + code], cwd=cwd, capture_output=True, text=True, timeout=60)

    def test_mysearx_imports_nothing_from_the_toolkit(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copy(ROOT / "mysearx.py", tmp)
            done = self.run_py(f"sys.path.insert(0, {tmp!r})\nimport mysearx\nprint(mysearx.build_query('Hello brave world'))", tmp)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "Hello brave world")

    def test_myollama_needs_only_mymessages(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("myollama.py", "mymessages.py"):
                shutil.copy(ROOT / name, tmp)
            done = self.run_py(f"sys.path.insert(0, {tmp!r})\nimport myollama\nprint(sorted(myollama.available_prompts()))", tmp)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("query_expand", done.stdout)

    def test_myollama_with_a_dictionary_prompt_does_not_even_need_mymessages(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copy(ROOT / "myollama.py", tmp)
            done = self.run_py(f"sys.path.insert(0, {tmp!r})\nimport myollama\nprint(myollama.resolve_prompt({{'role':'system','content':'x'}})['content'])", tmp)
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "x"), done.stderr)

    def test_no_toolkit_import_in_the_source(self):
        import re

        for name in ("mysearx.py", "myollama.py"):
            source = (ROOT / name).read_text(encoding="utf-8")
            imported = set(re.findall(r"^\s*(?:from|import)\s+([A-Za-z_][\w]*)", source, re.MULTILINE))
            toolkit = {"util", "myconfig", "openrouter", "content_urls", "content_creation", "content_expand", "rich", "colorama", "dotenv", "ollama", "requests"}
            self.assertEqual(imported & toolkit, set(), name)


class FakeOllama:
    """Answers POST /api/chat like Ollama: echoes the prompt and the text."""

    def __init__(self):
        self.bodies = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.bodies.append(body)
                if body["model"] == "missing":
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(b'{"error": "model \'missing\' not found"}')
                    return
                reply = {"message": {"role": "assistant", "content": "<think>hmm</think>ANSWER(" + body["messages"][1]["content"] + ")"}, "done": True}
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(reply).encode())

            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"models": [{"name": "b:1"}, {"name": "a:2"}]}')

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class OllamaModule(unittest.TestCase):
    def setUp(self):
        import myollama

        self.M = myollama
        self.fake = FakeOllama()
        self.addCleanup(self.fake.close)
        env = {"BASE_URL": self.fake.url, "MYMODEL_QUERY": "m1", "OLLAMA_NUM_CTX": "4096"}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        q = mock.patch.object(myollama, "_dotenv_values", return_value={})
        q.start()
        self.addCleanup(q.stop)

    def test_call_and_think_block(self):
        self.assertEqual(self.M.call_ollama("hello", show=False), "ANSWER(hello)")
        body = self.fake.bodies[-1]
        self.assertEqual(body["model"], "m1")
        self.assertFalse(body["stream"])
        self.assertEqual(body["messages"][0], mymessages.query_expand)
        self.assertEqual(body["options"], {"temperature": 0.7, "num_predict": 10000, "num_ctx": 4096})

    def test_prompt_by_name_dictionary_and_old_keyword(self):
        self.M.call_ollama("x", prompt="check_proof", show=False)
        self.assertEqual(self.fake.bodies[-1]["messages"][0], mymessages.check_proof)
        own = {"role": "system", "content": "mine"}
        self.M.call_ollama("x", prompt=own, show=False)
        self.assertEqual(self.fake.bodies[-1]["messages"][0], own)
        self.M.call_ollama("x", system_prompt="check_proof", show=False)
        self.assertEqual(self.fake.bodies[-1]["messages"][0], mymessages.check_proof)

    def test_keep_thinking(self):
        self.assertIn("<think>", self.M.call_ollama("x", show=False, strip_thinking=False))

    def test_errors(self):
        with self.assertRaises(RuntimeError) as ctx:
            self.M.call_ollama("x", model_name="missing", show=False)
        self.assertIn("ollama pull missing", str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            self.M.call_ollama("x", prompt="nope", show=False)
        self.assertEqual(str(ctx.exception), "unknown prompt 'nope'. Available prompts: " + ", ".join(sorted(mymessages.available_prompts())))
        for kwargs in ({"content": ""}, {"content": "x", "temperature": 3}, {"content": "x", "max_tokens": 0}, {"content": "x" * 100_001}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.M.call_ollama(show=False, **kwargs)

    def test_unreachable(self):
        with mock.patch.dict(os.environ, {"BASE_URL": "127.0.0.1:1"}):
            with self.assertRaises(RuntimeError) as ctx:
                self.M.call_ollama("x", show=False)
        self.assertIn("ollama serve", str(ctx.exception))

    def test_show_prints_a_header_and_the_answer(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.M.call_ollama("hello")
        self.assertIn("Response from model m1", out.getvalue())
        self.assertIn("ANSWER(hello)", out.getvalue())

    def test_many_models(self):
        with contextlib.redirect_stdout(io.StringIO()):
            answers = self.M.call_ollamas("hi", models=["a", "missing", "b"])
        self.assertEqual(sorted(answers), ["a", "b"])  # the failing model is skipped
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(self.M.call_ollamas("hi", models=[]), {})
        self.assertIn("MODELS_NEWCONTENT", out.getvalue())

    def test_list_models(self):
        self.assertEqual(self.M.list_models(), ["a:2", "b:1"])

    def test_config_from_environment(self):
        with mock.patch.dict(os.environ, {"MODELS_NEWCONTENT": "a, b  c", "OLLAMA_TIMEOUT": "12"}):
            cfg = self.M.load_config()
        self.assertEqual((cfg.models, cfg.timeout, cfg.num_ctx), (("a", "b", "c"), 12.0, 4096))
        with mock.patch.dict(os.environ, {"OLLAMA_TIMEOUT": "fast"}):
            with self.assertRaises(ValueError):
                self.M.load_config()

    def test_cli(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(self.M.cli(["--raw", "--prompt", "check_proof", "teh", "text"]), 0)
        self.assertEqual(out.getvalue(), "ANSWER(teh text)\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(self.M.cli(["--list-models"]), 0)
        self.assertEqual(out.getvalue().split(), ["a:2", "b:1"])
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.M.cli(["--prompt", "nope", "x"]), 2)
            with mock.patch.object(sys, "stdin", io.StringIO("")):
                self.assertEqual(self.M.cli([]), 2)

    def test_cli_reads_standard_input(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.object(sys, "stdin", io.StringIO("from a pipe\n")):
            self.assertEqual(self.M.cli(["--raw"]), 0)
        self.assertEqual(out.getvalue(), "ANSWER(from a pipe)\n")


# --------------------------------------------------------------------------- #
# searx.sh (with a fake `docker` and a fake SearXNG)                          #
# --------------------------------------------------------------------------- #


@unittest.skipUnless(shutil.which("bash") and shutil.which("curl") and SCRIPT.is_file(), "needs bash, curl and searx.sh")
class ShellScript(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        shim = self.tmp / "bin"
        self.log = self.tmp / "docker.log"
        write(shim / "docker", f'#!/bin/bash\necho "docker $*" >> "{self.log}"\nexit 0\n')
        (shim / "docker").chmod(0o755)
        self.fake = FakeSearx()
        self.addCleanup(self.fake.close)
        port = self.fake.url.rsplit(":", 1)[1]
        self.env = dict(os.environ, PATH=f"{shim}:{os.environ['PATH']}", SEARX_PORT=port, SEARX_HOME=str(self.tmp / "home"),
                        SEARX_CONF=str(self.tmp / "none.conf"), NO_COLOR="1")

    def sh(self, *args, shell="bash"):
        return subprocess.run([shell, str(SCRIPT), *args], capture_output=True, text=True, env=self.env, timeout=120)

    def test_install_writes_a_config_that_enables_json_and_binds_to_localhost(self):
        done = self.sh("install")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        settings = (self.tmp / "home" / "config" / "settings.yml").read_text()
        self.assertIn("- json", settings)
        self.assertIn("limiter: false", settings)
        self.assertRegex(settings, r'secret_key: "[0-9a-f]{64}"')
        compose = (self.tmp / "home" / "docker-compose.yml").read_text()
        self.assertIn(f'"127.0.0.1:{self.env["SEARX_PORT"]}:8080"', compose)
        self.assertIn('restart: "no"', compose)
        self.assertNotIn("unless-stopped", compose)
        self.assertIn("pull", self.log.read_text())

    def test_existing_config_is_never_overwritten(self):
        self.sh("install")
        settings = self.tmp / "home" / "config" / "settings.yml"
        settings.write_text(settings.read_text() + "# my edit\n")
        self.sh("start")
        self.assertIn("# my edit", settings.read_text())

    def test_a_config_without_json_is_reported(self):
        self.sh("install")
        settings = self.tmp / "home" / "config" / "settings.yml"
        settings.write_text(settings.read_text().replace("- json", "- csv"))
        done = self.sh("start")
        self.assertIn("json format", done.stderr)

    def test_start_when_it_already_answers(self):
        done = self.sh("start")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("already running", done.stdout)

    def test_test_command_does_a_json_search(self):
        done = self.sh("test")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("JSON search works", done.stdout)
        self.assertIn("Faraday's law", done.stdout)

    def test_test_command_explains_a_403(self):
        self.fake.mode = "403"
        done = self.sh("test")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("json format is not enabled", done.stderr)

    def test_stop_removes_the_container(self):
        self.sh("install")
        done = self.sh("stop", "--keep-docker")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn(" down", self.log.read_text())

    def test_stop_without_our_marker_does_not_quit_docker(self):
        self.sh("install")
        done = self.sh("stop")
        self.assertNotIn("Quitting", done.stdout)

    def test_runs_under_sh_too(self):
        done = self.sh("paths", shell="sh")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("settings:", done.stdout)

    def test_unknown_command(self):
        self.assertEqual(self.sh("bogus").returncode, 2)

    def test_help_lists_the_commands(self):
        out = self.sh("help").stdout
        for word in ("install", "start", "stop", "update", "status", "logs"):
            self.assertIn(f"searx.sh {word}", out)

    def stale_docker(self, rm_fails=False, up_fails_always=False):
        """A docker shim that behaves like the broken Docker of the bug report: a leftover
        container makes `compose up` fail with 'RWLayer ... is unexpectedly nil'."""
        state = self.tmp / "state"
        state.write_text("stale")
        script = f"""#!/bin/bash
echo "docker $*" >> "{self.log}"
S="{state}"
case "$1 $2" in
  "ps -a") [ "$(cat $S)" = stale ] && echo searxng; exit 0 ;;
  "rm -f") {"echo 'RWLayer unexpectedly nil' >&2; exit 1" if rm_fails else 'echo clean > $S; exit 0'} ;;
  "rename searxng") echo clean > $S; exit 0 ;;
esac
if [ "$1" = compose ]; then
  case "$*" in
    *" up "*) {"echo 'RWLayer of container x is unexpectedly nil' >&2; exit 1" if up_fails_always else '[ "$(cat $S)" = stale ] && { echo "RWLayer of container x is unexpectedly nil" >&2; exit 1; }; exit 0'} ;;
  esac
fi
exit 0
"""
        write(self.tmp / "bin" / "docker", script)
        (self.tmp / "bin" / "docker").chmod(0o755)

    def run_start_when_down(self):
        """`searx.sh start` while nothing answers (the fake docker cannot start a server, so the
        script ends by timing out; the tests look at the docker calls it made)."""
        self.fake.close()
        return subprocess.run(["bash", str(SCRIPT), "start"], capture_output=True, text=True,
                              env=dict(self.env, SEARX_WAIT="3"), timeout=60)

    def test_a_stale_container_is_removed_before_starting(self):
        self.stale_docker()
        done = self.run_start_when_down()
        log = self.log.read_text()
        self.assertIn("docker rm -f searxng", log)
        self.assertLess(log.index("docker rm -f searxng"), log.index(" up -d"))
        self.assertIn("leftover", done.stdout + done.stderr)

    def test_if_removal_fails_the_stale_container_is_renamed_out_of_the_way(self):
        self.stale_docker(rm_fails=True)
        self.run_start_when_down()
        self.assertIn("docker rename searxng searxng-stale-", self.log.read_text())

    def test_a_start_that_keeps_failing_explains_what_to_do(self):
        self.stale_docker(up_fails_always=True)
        done = self.run_start_when_down()
        out = done.stdout + done.stderr
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(self.log.read_text().count(" up -d"), 2)  # tried once, cleaned, tried again
        self.assertIn("RWLayer", out)
        self.assertIn("Purge data", out)

    def test_a_running_container_is_never_removed(self):
        # `docker ps` lists searxng as running -> remove_stale_container must leave it alone.
        write(self.tmp / "bin" / "docker", f"""#!/bin/bash
echo "docker $*" >> "{self.log}"
case "$1 $2" in "ps -a"|"ps --format") echo searxng ;; esac
exit 0
""")
        (self.tmp / "bin" / "docker").chmod(0o755)
        self.run_start_when_down()
        self.assertNotIn("docker rm -f", self.log.read_text())

    def test_python_can_drive_the_script(self):
        # The same pieces mysearx uses: find the script, run `stop`, port passed through the environment.
        cfg = S.SearxConfig(url=self.fake.url, script=SCRIPT)
        with mock.patch.dict(os.environ, self.env, clear=True):
            self.sh("install")
            S.stop(cfg, quit_docker=False)
        self.assertIn(" down", self.log.read_text())


if __name__ == "__main__":
    unittest.main()

    def test_reset_is_listed_in_the_help(self):
        self.assertIn("searx.sh reset", self.sh("help").stdout)

    def test_reset_removes_the_container_and_starts_again(self):
        self.sh("install")
        done = self.sh("reset")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("Resetting Docker and SearXNG", done.stdout + done.stderr)
        log = self.log.read_text()
        self.assertIn("rm -f searxng", log)

    def test_the_forced_quit_helper_exists_and_escalates(self):
        text = SCRIPT.read_text()
        self.assertIn("hard_quit_docker()", text)
        for needle in ("osascript -e 'quit app \"Docker\"'", "pkill -f \"Docker.app/Contents\"", "pkill -9"):
            self.assertIn(needle, text)


class ExpandStepCautions(unittest.TestCase):
    """Little growth is shown in the summary as a warning but the step is a proposal, not a problem."""

    def test_caution_is_not_a_problem(self):
        import content_creation as CC
        result = SimpleNamespace(serious=False, words_before=3152, words_after=3369, saved_to=None, warnings=[],
                                 cautions=["only 6% longer than the original (3152 -> 3369 words); free models often do this"])
        with mock.patch("content_expand.expand_article", return_value=result):
            status, detail = CC._step_expand(Path("x.md"), True)
        self.assertEqual(status, CC.PROPOSAL)
        self.assertIn("only 6% longer", detail)
        self.assertIn("3152 -> 3369", detail)


class BuildQueries(unittest.TestCase):
    def test_variants_best_first_without_duplicates(self):
        queries = S.build_queries("Faraday law of induction", ["emf"], "How a changing magnetic field makes a voltage", 4)
        self.assertEqual(queries[0], "Faraday law of induction")
        self.assertEqual(queries[1], "Faraday law of induction tutorial")
        self.assertEqual(len(queries), 4)
        self.assertEqual(len({q.lower() for q in queries}), 4)

    def test_count_is_respected_and_one_means_only_the_title(self):
        self.assertEqual(S.build_queries("Rust ownership", (), "", 1), ["Rust ownership"])
        self.assertLessEqual(len(S.build_queries("Rust ownership", ["lang"], "desc words here", 8)), 8)

    def test_a_suffix_already_in_the_title_is_not_repeated(self):
        queries = S.build_queries("Python tutorial for beginners", (), "", 6)
        self.assertNotIn("Python tutorial for beginners tutorial", queries)

    def test_nothing_to_search(self):
        self.assertEqual(S.build_queries("", (), ""), [])

    def test_query_stays_short(self):
        for q in S.build_queries("one two three four five six seven eight nine ten eleven twelve", ["t"], "", 8):
            self.assertLessEqual(len(q.split()), 12)


class Gather(unittest.TestCase):
    def setUp(self):
        self.cfg = S.SearxConfig(url="http://127.0.0.1:8080", limit=5, pages=2, fetch=False, delay=0.0)
        p = mock.patch.object(S, "_sleep")
        self.sleep = p.start()
        self.addCleanup(p.stop)

    def resp(self, *urls, **kw):
        return S.SearxResponse("q", [S.SearxResult(f"T {u}", f"https://{u}/p") for u in urls], total_found=len(urls), **kw)

    def run_gather(self, side_effect, queries=("a b c", "a b c tutorial"), **kw):
        with mock.patch.object(S, "search", side_effect=side_effect) as search:
            return S.gather(list(queries), config=self.cfg, **kw), search

    def test_every_query_and_page_is_searched_and_merged(self):
        answer, search = self.run_gather(lambda q, **k: self.resp("one.org", "two.org") if k["pageno"] == 1 else self.resp("three.org"))
        self.assertEqual(search.call_count, 4)  # 2 queries x 2 pages
        self.assertEqual({r.url for r in answer.results}, {"https://one.org/p", "https://two.org/p", "https://three.org/p"})
        self.assertEqual(answer.searches, 4)
        self.assertEqual(answer.queries, ["a b c", "a b c tutorial"])

    def test_a_link_found_by_several_queries_ranks_first(self):
        def fake(q, **k):
            if k["pageno"] > 1:
                return self.resp()
            return self.resp("first.org", "common.org") if q == "a b c" else self.resp("other.org", "common.org")
        answer, _ = self.run_gather(fake)
        self.assertEqual(answer.results[0].url, "https://common.org/p")

    def test_an_empty_page_stops_the_paging_of_that_query(self):
        answer, search = self.run_gather(lambda q, **k: self.resp() , queries=("only one",))
        self.assertEqual(search.call_count, 1)

    def test_one_failing_query_does_not_stop_the_others(self):
        def fake(q, **k):
            if q == "a b c":
                raise S.SearxError("HTTP 500")
            return self.resp("ok.org") if k["pageno"] == 1 else self.resp()
        answer, _ = self.run_gather(fake)
        self.assertEqual([r.url for r in answer.results], ["https://ok.org/p"])
        self.assertTrue(any("HTTP 500" in e for e in answer.errors))

    def test_all_failing_raises(self):
        with self.assertRaises(S.SearxError):
            self.run_gather(S.SearxError("boom"))

    def test_not_running_is_raised_at_once(self):
        with self.assertRaises(S.SearxNotRunning):
            self.run_gather(S.SearxNotRunning("down"))

    def test_the_pause_between_searches(self):
        self.cfg = S.SearxConfig(url="http://127.0.0.1:8080", pages=1, fetch=False, delay=2.5)
        self.run_gather(lambda q, **k: self.resp("x.org"))
        self.sleep.assert_called_with(2.5)
        self.assertEqual(self.sleep.call_count, 1)  # not before the first search

    def test_unresponsive_answers_suggestions_are_merged_once(self):
        answer, _ = self.run_gather(lambda q, **k: self.resp("x.org", unresponsive=["google: captcha"], suggestions=["s1"]) if k["pageno"] == 1 else self.resp())
        self.assertEqual(answer.unresponsive, ["google: captcha"])
        self.assertEqual(answer.suggestions, ["s1"])

    def test_bad_arguments(self):
        with self.assertRaises(ValueError):
            S.gather([], config=self.cfg)
        with self.assertRaises(ValueError):
            S.gather("x", pages=99, config=self.cfg)

    def test_pages_are_downloaded_for_the_best_results(self):
        self.cfg = S.SearxConfig(url="http://127.0.0.1:8080", pages=1, fetch=True, fetch_pages=2, delay=0.0)
        texts = {"https://a.org/p": "A text " * 50, "https://b.org/p": ""}

        def fake_fetch(url, max_chars=0, timeout=0):
            if not texts.get(url):
                raise S.SearxError("HTTP 404")
            return texts[url]

        with mock.patch.object(S, "fetch_page_text", side_effect=fake_fetch):
            answer, _ = self.run_gather(lambda q, **k: self.resp("a.org", "b.org", "c.org"), queries=("one",))
        self.assertEqual(list(answer.pages), ["https://a.org/p"])
        self.assertTrue(any("b.org" in e and "404" in e for e in answer.errors))

    def test_pdfs_are_not_downloaded(self):
        self.cfg = S.SearxConfig(url="http://127.0.0.1:8080", pages=1, fetch=True, fetch_pages=5, delay=0.0)
        pdf = S.SearxResponse("q", [S.SearxResult("P", "https://a.org/file.pdf")])
        with mock.patch.object(S, "fetch_page_text") as fetch:
            self.run_gather(lambda q, **k: pdf, queries=("one",))
        fetch.assert_not_called()


class FetchPage(unittest.TestCase):
    HTML = ("<html><head><title>x</title><script>var a=1;</script></head><body><nav>Home About Contact us today please</nav>"
            "<h1>Faraday's law</h1><p>" + "A changing magnetic flux induces an electromotive force in a loop. " * 4 + "</p>"
            "<footer>Copyright footer text that is long enough to pass the filter</footer></body></html>")

    class Reply:
        def __init__(self, body, kind="text/html", url="https://a.org/p"):
            import email.message
            self._body, self._url = body, url
            self.headers = email.message.Message()
            self.headers["Content-Type"] = kind + "; charset=utf-8"

        def read(self, n=-1):
            return self._body[:n] if n and n > 0 else self._body

        def geturl(self):
            return self._url

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fetch(self, html, **kw):
        reply = self.Reply(html.encode() if isinstance(html, str) else html, **kw)
        with mock.patch.object(S, "_public_host", return_value=True), mock.patch.object(S, "urlopen", return_value=reply):
            return S.fetch_page_text("https://a.org/p", 4000)

    def test_text_without_menus_scripts_and_footers(self):
        text = self.fetch(self.HTML)
        self.assertIn("## Faraday's law", text)
        self.assertIn("electromotive force", text)
        self.assertNotIn("var a=1", text)
        self.assertNotIn("Copyright footer", text)
        self.assertNotIn("Home About", text)

    def test_cut_to_the_limit_on_a_line(self):
        long_html = "<body>" + "".join(f"<p>{'Paragraph number %d of the page with enough words to count. ' % i * 2}</p>" for i in range(200)) + "</body>"
        with mock.patch.object(S, "_public_host", return_value=True), \
                mock.patch.object(S, "urlopen", return_value=self.Reply(long_html.encode())):
            text = S.fetch_page_text("https://a.org/p", 1000)
        self.assertLessEqual(len(text), 1000)

    def test_not_html_and_not_text(self):
        with self.assertRaises(S.SearxError):
            self.fetch(b"%PDF", kind="application/pdf")

    def test_nearly_empty_page(self):
        with self.assertRaises(S.SearxError):
            self.fetch("<p>short</p>")

    def test_private_and_bad_addresses_are_refused(self):
        for url in ("http://127.0.0.1/x", "http://192.168.1.5/", "http://localhost/", "ftp://a.org/f", "file:///etc/passwd", "javascript:1"):
            with self.assertRaises(S.SearxError, msg=url):
                S.fetch_page_text(url)

    def test_a_redirect_to_a_private_address_is_refused(self):
        reply = self.Reply(self.HTML.encode(), url="http://192.168.0.9/admin")
        with mock.patch.object(S, "_public_host", side_effect=lambda h: h == "a.org"), mock.patch.object(S, "urlopen", return_value=reply):
            with self.assertRaises(S.SearxError):
                S.fetch_page_text("https://a.org/p")

    def test_public_host_check(self):
        with mock.patch.object(S.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 0))]):
            self.assertTrue(S._public_host("example.org"))
        with mock.patch.object(S.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("10.0.0.5", 0))]):
            self.assertFalse(S._public_host("intranet"))
        with mock.patch.object(S.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 0)), (2, 1, 6, "", ("127.0.0.1", 0))]):
            self.assertFalse(S._public_host("mixed"))
        with mock.patch.object(S.socket, "getaddrinfo", side_effect=OSError):
            self.assertFalse(S._public_host("nowhere.invalid"))
        self.assertFalse(S._public_host(""))


class DeepContext(unittest.TestCase):
    def response(self):
        results = [S.SearxResult(f"Title {i}", f"https://s{i}.org/p", f"snippet {i}") for i in range(1, 4)]
        return S.SearxResponse("q", results, pages={"https://s1.org/p": "line one of text\n" * 100, "https://s3.org/p": "third page text " * 50})

    def test_excerpts_follow_the_list_and_fit_the_budget(self):
        text = S.as_context(self.response(), max_chars=3000)
        self.assertLessEqual(len(text), 3000)
        self.assertIn("PAGE EXCERPTS", text)
        self.assertIn("--- [1] Title 1", text)
        self.assertIn("--- [3] Title 3", text.replace("--- [2]", ""))
        self.assertLess(text.index("[3] Title 3 (s3.org)"), text.index("PAGE EXCERPTS"))

    def test_without_pages_the_format_is_unchanged(self):
        response = self.response()
        response.pages = {}
        self.assertNotIn("PAGE EXCERPTS", S.as_context(response))

    def test_config_limits(self):
        env = {"SEARX_QUERIES": "20"}
        with mock.patch.dict(os.environ, env), mock.patch.object(S, "_dotenv_values", return_value={}):
            with self.assertRaises(S.SearxError):
                S.load_config()
        with mock.patch.dict(os.environ, {"SEARX_FETCH": "0", "SEARX_PAGES": "3", "SEARX_CONTEXT_CHARS": "50000"}), \
                mock.patch.object(S, "_dotenv_values", return_value={}):
            cfg = S.load_config()
        self.assertFalse(cfg.fetch)
        self.assertEqual((cfg.pages, cfg.context_chars, cfg.queries), (3, 50000, 4))

    def test_pageno_is_sent_from_the_second_page(self):
        calls = []

        class R:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, n=-1):
                return b'{"results": []}'

        def fake(request, timeout=0):
            calls.append(request.full_url)
            return R()

        with mock.patch.object(S, "urlopen", fake):
            S.search("x y z", pageno=1, config=S.SearxConfig())
            S.search("x y z", pageno=3, config=S.SearxConfig())
        self.assertNotIn("pageno", calls[0])
        self.assertIn("pageno=3", calls[1])
        with self.assertRaises(ValueError):
            S.search("x", pageno=0, config=S.SearxConfig())


class DeepResearchPage(unittest.TestCase):
    def test_deep_uses_gather_with_the_query_variants(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        page = write(Path(tmp.name) / "p.md", "---\ntitle: Faraday law of induction\ndescription: voltage from a changing field\n---\nBody\n")
        response = S.SearxResponse("a | b", [S.SearxResult("T", "https://a.org/x")], queries=["a", "b"],
                                   pages={"https://a.org/x": "text " * 100}, errors=["download x.org: HTTP 404"])
        cfg = S.SearxConfig(url="http://127.0.0.1:8080")
        with mock.patch.object(S, "load_config", return_value=cfg), mock.patch.object(S, "is_up", return_value=True), \
                mock.patch.object(S, "running", lambda *a, **k: contextlib.nullcontext(False)), \
                mock.patch.object(S, "gather", return_value=response) as gather, mock.patch.object(S, "search") as plain, \
                contextlib.redirect_stdout(io.StringIO()):
            research = CS.research_page(page)
        queries = gather.call_args.args[0]
        self.assertGreater(len(queries), 1)
        self.assertEqual(queries[0], "Faraday law of induction")
        plain.assert_not_called()
        self.assertIn("PAGE EXCERPTS", research.text)
        self.assertTrue(any("HTTP 404" in n for n in research.notes))


class ForcedRestart(unittest.TestCase):
    """Docker is restarted NO MATTER WHAT when SearXNG will not come up (reset command)."""

    def cfg(self, **kw):
        return S.SearxConfig(url="http://127.0.0.1:8080", **kw)

    def test_failed_start_falls_back_to_reset(self):
        calls = []

        def script(args, cfg, timeout):
            calls.append(args[0])
            if args[0] == "start":
                raise S.SearxError("searx.sh start failed (exit 1): Docker did not start")
            return ""

        with mock.patch.object(S, "is_up", side_effect=[False, True]), mock.patch.object(S, "_run_script", side_effect=script), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertTrue(S.start(self.cfg()))
        self.assertEqual(calls, ["start", "reset"])
        self.assertIn("Restarting Docker no matter what", err.getvalue())

    def test_start_that_returns_but_does_not_answer_also_resets(self):
        calls = []
        with mock.patch.object(S, "is_up", side_effect=[False, False, True]), \
                mock.patch.object(S, "_run_script", side_effect=lambda a, c, t: calls.append(a[0]) or ""), \
                contextlib.redirect_stderr(io.StringIO()):
            S.start(self.cfg())
        self.assertEqual(calls, ["start", "reset"])

    def test_restart_can_be_turned_off(self):
        calls = []

        def script(args, cfg, timeout):
            calls.append(args[0])
            raise S.SearxError("boom")

        with mock.patch.object(S, "is_up", return_value=False), mock.patch.object(S, "_run_script", side_effect=script):
            with self.assertRaises(S.SearxError):
                S.start(self.cfg(restart_on_fail=False))
        self.assertEqual(calls, ["start"])

    def test_still_down_after_the_reset_is_an_error(self):
        with mock.patch.object(S, "is_up", return_value=False), mock.patch.object(S, "_run_script", return_value=""):
            with self.assertRaises(S.SearxError) as ctx:
                S.reset(self.cfg())
        self.assertIn("still does not answer", str(ctx.exception))

    def test_reset_is_only_for_a_local_searxng(self):
        with self.assertRaises(S.SearxNotRunning):
            S.reset(S.SearxConfig(url="https://searx.example.org"))

    def test_setting_in_the_environment(self):
        with mock.patch.dict(os.environ, {"SEARX_RESTART": "0"}):
            self.assertFalse(S.load_config().restart_on_fail)
        with mock.patch.dict(os.environ, {"SEARX_RESTART": "1"}):
            self.assertTrue(S.load_config().restart_on_fail)

    def test_search_that_loses_searxng_restarts_once_and_retries(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        page = write(Path(tmp.name) / "p.md", "---\ntitle: Faraday law of induction\n---\nBody\n")
        response = S.SearxResponse("q", [S.SearxResult("T", "https://a.org/x")], queries=["q"])
        cfg = self.cfg()
        gather = mock.Mock(side_effect=[S.SearxNotRunning("SearXNG does not answer"), response])
        with mock.patch.object(S, "load_config", return_value=cfg), mock.patch.object(S, "is_up", return_value=True), \
                mock.patch.object(S, "running", lambda *a, **k: contextlib.nullcontext(False)), \
                mock.patch.object(S, "gather", gather), mock.patch.object(S, "reset") as reset, \
                contextlib.redirect_stdout(io.StringIO()):
            research = CS.research_page(page)
        reset.assert_called_once()
        self.assertEqual(gather.call_count, 2)
        self.assertTrue(any("Docker was restarted" in n for n in research.notes))

    def test_no_restart_when_it_is_disabled(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        page = write(Path(tmp.name) / "p.md", "---\ntitle: Faraday law of induction\n---\nBody\n")
        cfg = self.cfg(restart_on_fail=False)
        with mock.patch.object(S, "load_config", return_value=cfg), mock.patch.object(S, "is_up", return_value=True), \
                mock.patch.object(S, "running", lambda *a, **k: contextlib.nullcontext(False)), \
                mock.patch.object(S, "gather", side_effect=S.SearxNotRunning("down")), mock.patch.object(S, "reset") as reset, \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(S.SearxNotRunning):
                CS.research_page(page)
        reset.assert_not_called()
