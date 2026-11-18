"""myquicklinks.py and split_prefix: the web searches."""

import unittest

import support
from myquicklinks import Quicklink, build_url, load_quicklinks, parse_quicklinks, site_name
from mysearch import split_prefix
from mytypes import ConfigError


class Building(unittest.TestCase):
    def test_placeholder_is_replaced(self):
        link = Quicklink("g", "https://www.google.com/search?q={query}&hl=en", "google.com")
        self.assertEqual(build_url(link, "hello"), "https://www.google.com/search?q=hello&hl=en")

    def test_without_placeholder_the_query_goes_at_the_end(self):
        link = Quicklink("jttp", "https://justtothepoint.com/search/?query=", "x")
        self.assertEqual(build_url(link, "python tips"), "https://justtothepoint.com/search/?query=python+tips")

    def test_special_characters_are_encoded(self):
        link = Quicklink("g", "https://x.test/?q={query}", "x")
        self.assertEqual(build_url(link, "c++ & más"), "https://x.test/?q=c%2B%2B+%26+m%C3%A1s")

    def test_empty_query(self):
        link = Quicklink("g", "https://x.test/?q={query}", "x")
        self.assertEqual(build_url(link, "   "), "https://x.test/?q=")

    def test_site_name(self):
        self.assertEqual(site_name("https://www.youtube.com/results?x=1"), "youtube.com")
        self.assertEqual(site_name("http://localhost:8000/a"), "localhost")


class Parsing(unittest.TestCase):
    def bad(self, data, *words):
        with self.assertRaises(ConfigError) as ctx:
            parse_quicklinks(data, "q.json", reserved=("kill",))
        for word in words:
            self.assertIn(word, str(ctx.exception))

    def test_valid(self):
        links = parse_quicklinks([{"keyword": "YT", "url": "https://www.youtube.com/r?q={query}"}, {"keyword": "a", "url": "http://a.test/", "title": " A "}])
        self.assertEqual([(l.keyword, l.title) for l in links], [("yt", "youtube.com"), ("a", "A")])

    def test_errors_name_the_entry(self):
        self.bad({}, "must be a list")
        self.bad(["x"], "q.json[0]")
        self.bad([{"url": "https://a.test"}], "q.json[0].keyword")
        self.bad([{"keyword": "two words", "url": "https://a.test"}], "ONE word")
        self.bad([{"keyword": "", "url": "https://a.test"}], "keyword")
        self.bad([{"keyword": "a"}], "q.json[0].url")
        self.bad([{"keyword": "a", "url": "ftp://a.test"}], "http")
        self.bad([{"keyword": "a", "url": "javascript:alert(1)"}], "http")
        self.bad([{"keyword": "a", "url": "https://a.test", "title": 3}], "title")

    def test_duplicates_and_reserved(self):
        url = "https://a.test"
        self.bad([{"keyword": "a", "url": url}, {"keyword": "A", "url": url}], "twice")
        self.bad([{"keyword": "kill", "url": url}], "reserved")


class Loading(support.TempDirCase):
    def test_missing_file_means_no_quicklinks(self):
        self.assertEqual(load_quicklinks(self.tmp / "nope.json"), ())

    def test_invalid_json_says_where(self):
        path = self.tmp / "q.json"
        path.write_text("[\n {,\n]")
        with self.assertRaises(ConfigError) as ctx:
            load_quicklinks(path)
        self.assertIn("line 2", str(ctx.exception))

    def test_the_shipped_file_has_the_three_examples(self):
        links = load_quicklinks(support.ROOT / "conf" / "quicklinks.json", reserved=("kill",))
        self.assertEqual({l.keyword: l.url for l in links}, {
            "jttp": "https://justtothepoint.com/search/?query=",
            "google": "https://www.google.com/search?q={query}",
            "yt": "https://www.youtube.com/results?search_query={query}",
        })


class SplitPrefix(unittest.TestCase):
    def test_cases(self):
        self.assertEqual(split_prefix("yt lofi beats"), ("yt", "lofi beats"))
        self.assertEqual(split_prefix("YT  lofi  "), ("yt", "lofi"))
        self.assertEqual(split_prefix("yt "), ("yt", ""))
        self.assertEqual(split_prefix("  yt x"), ("yt", "x"))
        self.assertIsNone(split_prefix("yt"))
        self.assertIsNone(split_prefix(""))
        self.assertIsNone(split_prefix("   "))


if __name__ == "__main__":
    unittest.main()
