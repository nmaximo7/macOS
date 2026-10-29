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
        with mock.patch("myconfig.get_settings", return_value=SimpleNamespace(hugo_root=None)):
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
        with mock.patch("myconfig.get_settings", return_value=SimpleNamespace(hugo_root=None)):
            self.assertEqual(self.run_main("/does/not/exist.md"), 2)

    def test_counted(self):
        self.assertEqual(CC._counted(-1, "link")[0], CC.UNCHECKED)
        self.assertEqual(CC._counted(0, "link")[0], CC.OK)
        self.assertEqual(CC._counted(3, "link"), (CC.PROBLEMS, "3 link problem(s)"))

    def test_status_needs_attention(self):
        flags = {s: CC.StepResult("k", "K", s).needs_attention for s in (CC.OK, CC.PROPOSAL, CC.PROBLEMS, CC.UNCHECKED, CC.ERROR)}
        self.assertEqual(flags, {CC.OK: False, CC.PROPOSAL: False, CC.PROBLEMS: True, CC.UNCHECKED: True, CC.ERROR: True})

    def test_crashing_step_does_not_stop_the_others(self):
        def boom(page, show_ok):
            raise RuntimeError("kaput")

        def fine(page, show_ok):
            return CC.OK, "fine"

        steps = [("a", "A", boom), ("b", "B", fine)]
        with mock.patch.object(CC, "STEPS", steps), contextlib.redirect_stdout(io.StringIO()):
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
        with mock.patch.object(CC, "STEPS", steps), contextlib.redirect_stdout(io.StringIO()):
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
        self.assertEqual(LC.local_file_for(self.public, "/a/b/"), self.public / "a" / "b" / "index.html")

    def test_root(self):
        self.assertEqual(LC.local_file_for(self.public, "/"), self.public / "index.html")

    def test_directory_url_without_final_slash(self):
        self.assertEqual(LC.local_file_for(self.public, "/a/b"), self.public / "a" / "b" / "index.html")

    def test_html_extension_is_added(self):
        self.assertEqual(LC.local_file_for(self.public, "/page"), self.public / "page.html")

    def test_url_encoded_names(self):
        self.assertEqual(LC.local_file_for(self.public, "/img/my%20pic.png"), self.public / "img" / "my pic.png")

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
