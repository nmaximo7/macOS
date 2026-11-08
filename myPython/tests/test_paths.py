"""content_creation.find_page / main exit codes and link_checker_page.local_file_for."""

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import content_creation as CC
import link_checker_page as LC


def touch(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class FindPage(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.page = touch(self.root / "content" / "calculus" / "p.md")
        settings = SimpleNamespace(hugo_root=self.root)
        patcher = mock.patch("myconfig.get_settings", return_value=settings)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_absolute_path(self):
        path, _ = CC.find_page(str(self.page))
        self.assertEqual(path, self.page)

    def test_relative_to_hugo_root(self):
        path, tried = CC.find_page("content/calculus/p.md")
        self.assertEqual(path, self.page)
        self.assertEqual(len(tried), 2)

    def test_relative_to_content(self):
        path, tried = CC.find_page("calculus/p.md")
        self.assertEqual(path, self.page)
        self.assertEqual(len(tried), 3)

    def test_not_found_lists_the_places_tried(self):
        path, tried = CC.find_page("nope/x.md")
        self.assertIsNone(path)
        self.assertEqual(len(tried), 3)

    def test_without_hugo_root_only_the_given_path_is_tried(self):
        with mock.patch(
            "myconfig.get_settings", return_value=SimpleNamespace(hugo_root=None)
        ):
            path, tried = CC.find_page("calculus/p.md")
        self.assertIsNone(path)
        self.assertEqual(len(tried), 1)

    def test_broken_configuration_does_not_crash(self):
        with mock.patch("myconfig.get_settings", side_effect=ValueError("bad .env")):
            self.assertEqual(CC.find_page("calculus/p.md")[0], None)


class MainExitCodes(unittest.TestCase):
    def run_main(self, *args, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return CC.main(*args, **kwargs)

    def test_missing_page_is_exit_code_2(self):
        with mock.patch(
            "myconfig.get_settings", return_value=SimpleNamespace(hugo_root=None)
        ):
            self.assertEqual(self.run_main("/does/not/exist.md"), 2)

    def test_counted(self):
        self.assertEqual(CC._counted(-1, "link")[0], CC.UNCHECKED)
        self.assertEqual(CC._counted(0, "link")[0], CC.OK)
        self.assertEqual(CC._counted(3, "link"), (CC.PROBLEMS, "3 link problem(s)"))

    def test_status_needs_attention(self):
        flags = {
            s: CC.StepResult("k", "K", s).needs_attention
            for s in (CC.OK, CC.PROPOSAL, CC.PROBLEMS, CC.UNCHECKED, CC.ERROR)
        }
        self.assertEqual(
            flags,
            {
                CC.OK: False,
                CC.PROPOSAL: False,
                CC.PROBLEMS: True,
                CC.UNCHECKED: True,
                CC.ERROR: True,
            },
        )

    def test_crashing_step_does_not_stop_the_others(self):
        def boom(page, show_ok):
            raise RuntimeError("kaput")

        def fine(page, show_ok):
            return CC.OK, "fine"

        steps = [("a", "A", boom), ("b", "B", fine)]
        with (
            mock.patch.object(CC, "STEPS", steps),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            results = CC.run_checks("x.md")
            code = CC.print_summary(results)
        self.assertEqual([r.status for r in results], [CC.ERROR, CC.OK])
        self.assertEqual(code, 1)

    def test_only_and_skip(self):
        ran = []

        def make(key):
            def step(page, show_ok):
                ran.append(key)
                return CC.OK, ""

            return step

        steps = [(k, k, make(k)) for k in ("a", "b", "c")]
        with (
            mock.patch.object(CC, "STEPS", steps),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            CC.run_checks("x.md", only=["a", "c"], skip=["c"])
        self.assertEqual(ran, ["a"])

    def test_clean_summary_is_exit_code_0(self):
        results = [CC.StepResult("a", "A", CC.OK), CC.StepResult("b", "B", CC.PROPOSAL)]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(CC.print_summary(results), 0)


class LocalFileFor(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.public = Path(self._tmp.name)
        touch(self.public / "index.html")
        touch(self.public / "a" / "b" / "index.html")
        touch(self.public / "page.html")
        touch(self.public / "img" / "my pic.png")
        touch(self.public / "File.txt")

    def test_directory_url(self):
        self.assertEqual(
            LC.local_file_for(self.public, "/a/b/"),
            self.public / "a" / "b" / "index.html",
        )

    def test_root(self):
        self.assertEqual(
            LC.local_file_for(self.public, "/"), self.public / "index.html"
        )

    def test_directory_url_without_final_slash(self):
        self.assertEqual(
            LC.local_file_for(self.public, "/a/b"),
            self.public / "a" / "b" / "index.html",
        )

    def test_html_extension_is_added(self):
        self.assertEqual(
            LC.local_file_for(self.public, "/page"), self.public / "page.html"
        )

    def test_url_encoded_names(self):
        self.assertEqual(
            LC.local_file_for(self.public, "/img/my%20pic.png"),
            self.public / "img" / "my pic.png",
        )

    def test_missing_file(self):
        self.assertIsNone(LC.local_file_for(self.public, "/nope/"))

    def test_never_leaves_public(self):
        self.assertIsNone(LC.local_file_for(self.public, "/../secret"))
        self.assertIsNone(LC.local_file_for(self.public, "/a/../index.html"))

    def test_capitals_must_match_exactly(self):
        self.assertIsNotNone(LC.local_file_for(self.public, "/File.txt"))
        self.assertIsNone(LC.local_file_for(self.public, "/file.txt"))

    def test_exact_file(self):
        self.assertTrue(LC._exact_file(self.public, ["a", "b", "index.html"]))
        self.assertFalse(LC._exact_file(self.public, ["a", "B", "index.html"]))
        self.assertFalse(LC._exact_file(self.public, ["a"]))  # a folder, not a file


if __name__ == "__main__":
    unittest.main()


class FindLatestPage(unittest.TestCase):
    """content_creation.find_latest_page: the page edited last, found in the content folder."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.content = Path(self._tmp.name).resolve() / "content"

    def page(self, rel, age_seconds, text="x"):
        path = touch(self.content / rel, text)
        import time

        stamp = time.time() - age_seconds
        os.utime(path, (stamp, stamp))
        return path

    def test_newest_wins(self):
        self.page("a/old.md", 5000)
        newest = self.page("b/c/new.md", 10)
        self.page("a/mid.md", 900)
        path, mtime = CC.find_latest_page(self.content)
        self.assertEqual(path, newest)
        self.assertGreater(mtime, 0)

    def test_empty_content_folder(self):
        self.content.mkdir(parents=True)
        self.assertEqual(CC.find_latest_page(self.content), (None, 0))

    def test_only_markdown_files_count(self):
        self.page("a/page.md", 5000)
        self.page("a/notes.txt", 1)
        self.page("a/pic.png", 1)
        self.page("a/page.html", 1)
        self.assertEqual(CC.find_latest_page(self.content)[0].name, "page.md")

    def test_markdown_extension_and_case(self):
        self.page("a/one.md", 500)
        newest = self.page("a/two.MARKDOWN", 5)
        self.assertEqual(CC.find_latest_page(self.content)[0], newest)

    def test_hidden_and_editor_files_are_ignored(self):
        keep = self.page("a/real.md", 5000)
        self.page(".git/hidden.md", 1)
        self.page("a/.hidden.md", 1)
        self.page("a/.#lock.md", 1)
        self.page("a/backup.md~", 1)
        self.assertEqual(CC.find_latest_page(self.content)[0], keep)

    def test_section_index_is_ignored_unless_asked(self):
        article = self.page("calculus/stokes.md", 5000)
        index = self.page("calculus/_index.md", 1)
        self.assertEqual(CC.find_latest_page(self.content)[0], article)
        self.assertEqual(
            CC.find_latest_page(self.content, include_index=True)[0], index
        )

    def test_leaf_bundle_index_md_is_a_real_page(self):
        bundle = self.page("calculus/stokes/index.md", 1)
        self.page("calculus/other.md", 5000)
        self.assertEqual(CC.find_latest_page(self.content)[0], bundle)

    def test_same_time_gives_a_stable_answer(self):
        a = self.page("a.md", 100)
        b = self.page("b.md", 100)
        os.utime(b, (os.stat(a).st_atime, os.stat(a).st_mtime))
        first = CC.find_latest_page(self.content)[0]
        self.assertEqual(first, CC.find_latest_page(self.content)[0])
        self.assertEqual(first.name, "b.md")

    def test_ago(self):
        self.assertEqual(CC._ago(3), "a few seconds ago")
        self.assertEqual(CC._ago(60), "1 minute ago")
        self.assertEqual(CC._ago(7300), "2 hours ago")
        self.assertEqual(CC._ago(3 * 86400 + 5), "3 days ago")


class NoPageGiven(unittest.TestCase):
    """python3 content_creation.py  (no argument)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.old = touch(self.root / "content" / "calculus" / "old.md")
        self.new = touch(self.root / "content" / "calculus" / "new.md")
        os.utime(self.old, (1_000_000, 1_000_000))

    def run_quiet(self, settings, *args, **kwargs):
        """Run CC.main with these settings; return (exit code, everything it printed)."""
        printed = []
        with (
            mock.patch("myconfig.get_settings", return_value=settings),
            mock.patch.object(
                CC.console,
                "print",
                side_effect=lambda *a, **k: printed.append(str(a[0]) if a else ""),
            ),
        ):
            code = CC.main(*args, **kwargs)
        return code, "\n".join(printed)

    def test_the_latest_page_is_checked(self):
        seen = []

        def fake_run_checks(page, only=None, skip=None, show_ok=True):
            seen.append(Path(page))
            return [CC.StepResult("a", "A", CC.OK)]

        with mock.patch.object(CC, "run_checks", fake_run_checks):
            code, out = self.run_quiet(SimpleNamespace(hugo_root=self.root))
        self.assertEqual(code, 0)
        self.assertEqual(seen, [self.new])
        self.assertIn("most recently modified", out)

    def test_options_are_passed_on(self):
        captured = {}

        def fake_run_checks(page, only=None, skip=None, show_ok=True):
            captured.update(only=only, skip=skip, show_ok=show_ok)
            return []

        with mock.patch.object(CC, "run_checks", fake_run_checks):
            self.run_quiet(
                SimpleNamespace(hugo_root=self.root), only=["links"], show_ok=False
            )
        self.assertEqual(captured, {"only": ["links"], "skip": None, "show_ok": False})

    def test_without_hugo_root_it_is_a_usage_error(self):
        code, out = self.run_quiet(SimpleNamespace(hugo_root=None))
        self.assertEqual(code, 2)
        self.assertIn("HUGO_ROOT", out)

    def test_missing_content_folder(self):
        code, out = self.run_quiet(SimpleNamespace(hugo_root=self.root / "nowhere"))
        self.assertEqual(code, 2)

    def test_no_markdown_at_all(self):
        empty = self.root / "empty"
        (empty / "content").mkdir(parents=True)
        code, out = self.run_quiet(SimpleNamespace(hugo_root=empty))
        self.assertEqual(code, 2)
        self.assertIn("no Markdown page", out)

    def test_cli_page_is_optional(self):
        with mock.patch.object(CC, "main", return_value=0) as main:
            self.assertEqual(CC.cli([]), 0)
        self.assertIsNone(main.call_args.args[0])

    def test_cli_passes_the_expand_options(self):
        with mock.patch.object(CC, "main", return_value=0) as main:
            CC.cli(
                [
                    "p.md",
                    "--provider",
                    "ollama",
                    "--model",
                    "m",
                    "--copy",
                    "--no-save",
                    "--include-index",
                ]
            )
        kw = main.call_args.kwargs
        self.assertEqual(
            kw["expand_options"],
            {
                "provider": "ollama",
                "model": "m",
                "temperature": None,
                "copy": True,
                "save": False,
            },
        )
        self.assertTrue(kw["include_index"])

    def test_cli_rejects_an_unknown_provider(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            CC.cli(["p.md", "--provider", "bing"])


class ExpandStep(unittest.TestCase):
    def test_expand_is_the_last_step_and_can_be_selected(self):
        self.assertEqual(CC.STEP_KEYS[-1], "expand")
        self.assertEqual(len(CC.STEP_KEYS), 8)
        self.assertEqual(
            CC.STEP_KEYS[-2], "searx"
        )  # the research must come BEFORE the rewrite that uses it

    def test_provider_names_match_the_configuration(self):
        import myconfig

        self.assertEqual(CC.EXPAND_PROVIDERS, myconfig.EXPAND_PROVIDERS)

    def result(self, **kw):
        import content_expand as E

        base = dict(
            text="t",
            provider="openrouter",
            model="m",
            words_before=10,
            words_after=30,
            seconds=1.0,
            saved_to=Path("/x/y.md"),
        )
        base.update(kw)
        return E.Expansion(**base)

    def test_clean_rewrite_is_a_proposal(self):
        with mock.patch("content_expand.expand_article", return_value=self.result()):
            status, detail = CC._step_expand(Path("p.md"), True)
        self.assertEqual(status, CC.PROPOSAL)
        self.assertIn("10 -> 30 words", detail)
        self.assertIn("/x/y.md", detail)

    def test_rewrite_with_warnings_is_a_problem(self):
        with (
            mock.patch(
                "content_expand.expand_article",
                return_value=self.result(warnings=["placeholder"]),
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            status, detail = CC._step_expand(Path("p.md"), True)
        self.assertEqual(status, CC.PROBLEMS)
        self.assertIn("1 issue", detail)

    def test_no_api_key_means_could_not_run(self):
        import content_expand as E

        with (
            mock.patch(
                "content_expand.expand_article",
                side_effect=E.ExpandError("No OpenRouter API key found.\n(more)"),
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            status, detail = CC._step_expand(Path("p.md"), True)
        self.assertEqual(status, CC.UNCHECKED)
        self.assertEqual(detail, "No OpenRouter API key found.")

    def test_options_reach_expand_article_and_do_not_leak_between_calls(self):
        calls = []

        def fake(page, **kwargs):
            calls.append(kwargs)
            return self.result()

        with (
            mock.patch("content_expand.expand_article", fake),
            mock.patch.object(CC, "find_page", return_value=(Path("p.md"), [])),
            mock.patch.object(
                CC, "STEPS", [("expand", "Expanded text", CC._step_expand)]
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            CC.main("p.md", expand_options={"provider": "ollama", "copy": True})
            CC.main("p.md")
        self.assertEqual(calls[0]["provider"], "ollama")
        self.assertTrue(calls[0]["copy"])
        self.assertIsNone(calls[1]["provider"])
        self.assertFalse(calls[1]["copy"])


class HowToFix(unittest.TestCase):
    """The summary tells the user which commands to try for each check that needs attention."""

    def _r(self, key, status, detail):
        return CC.StepResult(key, key, status, detail)

    def test_ok_and_proposal_have_no_hints(self):
        self.assertEqual(CC.how_to_fix(self._r("searx", CC.OK, "")), [])
        self.assertEqual(
            CC.how_to_fix(self._r("searx", CC.PROPOSAL, "8 result(s)")), []
        )

    def test_searx_not_running_points_to_the_script(self):
        text = "\n".join(
            CC.how_to_fix(
                self._r(
                    "searx",
                    CC.UNCHECKED,
                    "SearXNG is not running at http://127.0.0.1:8080",
                )
            )
        )
        self.assertIn("searx.sh start", text)
        self.assertIn("--skip searx", text)

    def test_searx_specific_errors(self):
        self.assertIn(
            "json",
            "\n".join(
                CC.how_to_fix(self._r("searx", CC.UNCHECKED, "HTTP 403"))
            ).lower(),
        )
        self.assertIn(
            "limiter",
            "\n".join(CC.how_to_fix(self._r("searx", CC.UNCHECKED, "HTTP 429"))),
        )
        self.assertIn(
            "docker rm -f searxng",
            "\n".join(
                CC.how_to_fix(
                    self._r(
                        "searx",
                        CC.UNCHECKED,
                        "RWLayer of container x is unexpectedly nil",
                    )
                )
            ),
        )
        self.assertIn(
            "--search",
            "\n".join(
                CC.how_to_fix(self._r("searx", CC.UNCHECKED, "no results for 'x'"))
            ),
        )

    def test_expand_key_and_ollama(self):
        self.assertIn(
            "--set-key",
            "\n".join(
                CC.how_to_fix(
                    self._r("expand", CC.UNCHECKED, "No OpenRouter API key found")
                )
            ),
        )
        self.assertIn(
            "ai-on",
            "\n".join(
                CC.how_to_fix(
                    self._r("expand", CC.UNCHECKED, "Ollama connection refused")
                )
            ),
        )

    def test_every_step_has_a_fallback_or_specific_hint(self):
        for key in CC.STEP_KEYS:
            if key == "searx" or key in CC._FIXES:
                self.assertTrue(CC._FIXES[key], key)
        self.assertTrue(
            CC.how_to_fix(self._r("links", CC.UNCHECKED, "could not be checked"))
        )

    def test_summary_prints_the_hints(self):
        lines = []

        class Capture:  # collects everything print_summary prints (stub-independent)
            def rule(self, *args, **kwargs):
                pass

            def print(self, *args, **kwargs):
                lines.extend(str(a) for a in args)

        results = [self._r("searx", CC.UNCHECKED, "SearXNG is not running")]
        with mock.patch.object(CC, "console", Capture()):
            code = CC.print_summary(results)
        text = "\n".join(lines)
        self.assertEqual(code, 1)
        self.assertIn("How to fix [searx]", text)
        self.assertIn("searx.sh start", text)
