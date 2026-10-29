"""content_urls: page -> URL, front matter helpers and the link/image scanner."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import content_urls as U


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class SiteCase(unittest.TestCase):
    """A throw-away Hugo site in a temporary folder."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        settings = SimpleNamespace(hugo_server="http://192.168.1.46:1313", hugo_root=self.root)
        patcher = mock.patch.object(U, "get_settings", return_value=settings)
        patcher.start()
        self.addCleanup(patcher.stop)

    def page(self, rel: str, text: str = "---\ntitle: T\n---\nbody\n") -> Path:
        return write(self.root / "content" / rel, text)


class ContentUrlPath(SiteCase):
    def test_plain_page(self):
        p = self.page("calculus/lineintegralspace.md")
        self.assertEqual(U._content_url_path(p, self.root), "/calculus/lineintegralspace/")

    def test_section_index(self):
        p = self.page("calculus/_index.md")
        self.assertEqual(U._content_url_path(p, self.root), "/calculus/")

    def test_page_bundle(self):
        p = self.page("posts/mybundle/index.md")
        self.assertEqual(U._content_url_path(p, self.root), "/posts/mybundle/")

    def test_home_page(self):
        p = self.page("_index.md")
        self.assertEqual(U._content_url_path(p, self.root), "/")

    def test_upper_case_and_spaces_follow_hugo(self):
        p = self.page("Linux/My Page.md")
        self.assertEqual(U._content_url_path(p, self.root), "/linux/my-page/")

    def test_url_in_front_matter_wins(self):
        p = self.page("a/b.md", "---\nurl: /custom/place/\n---\n")
        self.assertEqual(U._content_url_path(p, self.root), "/custom/place/")

    def test_url_without_leading_slash(self):
        p = self.page("a/b.md", '---\nurl: "custom/place/"\n---\n')
        self.assertEqual(U._content_url_path(p, self.root), "/custom/place/")

    def test_slug_replaces_the_last_segment(self):
        p = self.page("a/long-name.md", "---\nslug: short\n---\n")
        self.assertEqual(U._content_url_path(p, self.root), "/a/short/")

    def test_non_ascii_is_percent_encoded(self):
        p = self.page("a/año.md")
        self.assertEqual(U._content_url_path(p, self.root), "/a/a%C3%B1o/")

    def test_file_outside_content_is_an_error(self):
        outside = write(self.root / "static" / "x.md", "x")
        with self.assertRaises(ValueError):
            U._content_url_path(outside, self.root)


class PageUrl(SiteCase):
    def test_with_scheme(self):
        p = self.page("calculus/lineintegralspace.md")
        self.assertEqual(U.page_url(p), "http://192.168.1.46:1313/calculus/lineintegralspace/")

    def test_without_scheme(self):
        p = self.page("calculus/lineintegralspace.md")
        self.assertEqual(U.page_url(p, include_scheme=False), "192.168.1.46:1313/calculus/lineintegralspace/")

    def test_missing_server_is_a_clear_error(self):
        p = self.page("a.md")
        with mock.patch.object(U, "get_settings", return_value=SimpleNamespace(hugo_server="", hugo_root=self.root)):
            with self.assertRaises(U.HugoConfigError) as ctx:
                U.page_url(p)
        self.assertIn("HUGO_SERVER", str(ctx.exception))

    def test_missing_root_is_a_clear_error(self):
        p = self.page("a.md")
        with mock.patch.object(U, "get_settings", return_value=SimpleNamespace(hugo_server="http://x:1", hugo_root=None)):
            with self.assertRaises(U.HugoConfigError) as ctx:
                U.page_url(p)
        self.assertIn("HUGO_ROOT", str(ctx.exception))


class FrontMatterHelpers(unittest.TestCase):
    def test_front_len(self):
        self.assertEqual(U.front_len(["---", "a: 1", "---", "body"]), 3)
        self.assertEqual(U.front_len(["---", "a: 1", "...", "body"]), 3)
        self.assertEqual(U.front_len(["body", "---"]), 0)
        self.assertEqual(U.front_len(["---", "never closed"]), 0)
        self.assertEqual(U.front_len([]), 0)

    def test_front_len_ignores_a_bom(self):
        self.assertEqual(U.front_len(["﻿---", "a: 1", "---"]), 3)

    def test_unquote_value(self):
        self.assertEqual(U._unquote_value('"abc"'), "abc")
        self.assertEqual(U._unquote_value("'abc'"), "abc")
        self.assertEqual(U._unquote_value("abc  # comment"), "abc")
        self.assertEqual(U._unquote_value("  abc "), "abc")

    def test_read_lines_normalises_line_endings(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.md"
            p.write_bytes(b"a\r\nb\rc\n")
            self.assertEqual(U.read_lines(p), ["a", "b", "c", ""])

    def test_fields_of(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write(Path(tmp) / "x.md", '---\ntitle: "Hi"\nslug: s # note\n---\ntitle: not-front\n')
            self.assertEqual(U._fields_of(p), {"title": "Hi", "slug": "s"})
            self.assertEqual(U._fields_of(Path(tmp) / "missing.md"), {})


class UrlText(unittest.TestCase):
    def test_quote_path_keeps_existing_escapes(self):
        self.assertEqual(U._quote_path("/a/a%C3%B1o/"), "/a/a%C3%B1o/")
        self.assertEqual(U._quote_path("/a b/"), "/a%20b/")

    def test_safe_url_encodes_and_drops_fragment(self):
        self.assertEqual(
            U._safe_url("http://example.com/a b/ñ?q=1 2#frag"),
            "http://example.com/a%20b/%C3%B1?q=1%202",
        )

    def test_safe_url_idna_host(self):
        self.assertEqual(U._safe_url("http://bücher.example/x"), "http://xn--bcher-kva.example/x")

    def test_urlize(self):
        self.assertEqual(U._urlize("  My  Page "), "my-page")


class ScanPage(unittest.TestCase):
    def scan(self, body: str, front: str = ""):
        with tempfile.TemporaryDirectory() as tmp:
            p = write(Path(tmp) / "p.md", front + body)
            return U.scan_page(p)

    def targets(self, body: str, front: str = ""):
        return [(r.kind, r.target) for r in self.scan(body, front)]

    def test_markdown_link_and_image(self):
        got = self.targets("See [site](https://a.com/x) and ![alt](img/p.png)\n")
        self.assertEqual(got, [("link", "https://a.com/x"), ("image", "img/p.png")])

    def test_line_numbers_match_the_editor(self):
        front = "---\ntitle: T\n---\n"
        refs = self.scan("one\n[a](/x)\n", front)
        self.assertEqual([r.line for r in refs], [5])

    def test_code_is_skipped(self):
        body = "```\n[no](/fence)\n```\n`[no](/span)` [yes](/real)\n<!-- [no](/comment) -->\n"
        self.assertEqual(self.targets(body), [("link", "/real")])

    def test_html_anchor_and_image(self):
        got = self.targets('<a href="/a/">x</a> <img src="/i.png" alt="y">\n')
        self.assertIn(("link", "/a/"), got)
        self.assertIn(("image", "/i.png"), got)

    def test_autolink_and_bare_url(self):
        got = self.targets("<https://a.com/1> and https://b.com/2 end\n")
        self.assertEqual([t for _k, t in got], ["https://a.com/1", "https://b.com/2"])

    def test_reference_definition(self):
        refs = self.scan("[home]: https://a.com/\n")
        self.assertEqual([(r.source, r.target) for r in refs], [("definition", "https://a.com/")])

    def test_front_matter_image(self):
        refs = self.scan("body\n", "---\ntitle: T\nfeatured_image: /images/x.jpg\n---\n")
        self.assertIn(("image", "/images/x.jpg", "frontmatter"), [(r.kind, r.target, r.source) for r in refs])

    def test_empty_page(self):
        self.assertEqual(self.scan(""), [])


if __name__ == "__main__":
    unittest.main()
