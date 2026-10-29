"""content_quotes: the fortunes parser, the topics and the quote object."""

import unittest

import content_quotes as Q


class ParseFortunes(unittest.TestCase):
    def test_splits_on_percent_lines(self):
        raw = "First quote\n%\nSecond quote\n%\nThird\n"
        self.assertEqual([q.text for q in Q.parse_fortunes(raw)], ["First quote", "Second quote", "Third"])

    def test_author_line_is_separated(self):
        quotes = Q.parse_fortunes("Do or do not.\n    -- Yoda\n%\n")
        self.assertEqual(len(quotes), 1)
        self.assertEqual(quotes[0].text, "Do or do not.")
        self.assertEqual(quotes[0].author, "Yoda")

    def test_author_with_comma_and_dashes(self):
        for dash in ("--", "—", "–"):
            with self.subTest(dash=dash):
                q = Q.parse_fortunes(f"Text\n{dash} Mark Twain, Pudd'nhead Wilson")[0]
                self.assertEqual(q.author, "Mark Twain, Pudd'nhead Wilson")

    def test_single_line_starting_with_dash_is_not_an_author(self):
        q = Q.parse_fortunes("-- just a line")[0]
        self.assertEqual(q.author, "")
        self.assertEqual(q.text, "-- just a line")

    def test_multi_line_quote_keeps_line_breaks(self):
        q = Q.parse_fortunes("line one\nline two\n    -- Me")[0]
        self.assertEqual(q.text, "line one\nline two")

    def test_empty_blocks_are_ignored(self):
        self.assertEqual(Q.parse_fortunes("\n%\n\n%\n   \n"), [])
        self.assertEqual(Q.parse_fortunes(""), [])

    def test_windows_line_endings(self):
        quotes = Q.parse_fortunes("A\r\n%\r\nB\r\n    -- X\r\n")
        self.assertEqual([q.text for q in quotes], ["A", "B"])
        self.assertEqual(quotes[1].author, "X")

    def test_source_is_recorded(self):
        self.assertEqual(Q.parse_fortunes("A", source="file:tech")[0].source, "file:tech")

    def test_indentation_is_removed_but_relative_indent_kept(self):
        q = Q.parse_fortunes("    def f():\n        pass\n")[0]
        self.assertEqual(q.text, "def f():\n    pass")


class AsFortune(unittest.TestCase):
    def test_round_trip(self):
        q = Q.Quote(text="Hello", author="Me")
        self.assertEqual(q.as_fortune(), "Hello\n    -- Me")
        back = Q.parse_fortunes(q.as_fortune())[0]
        self.assertEqual((back.text, back.author), ("Hello", "Me"))

    def test_without_author(self):
        self.assertEqual(Q.Quote(text="Hello").as_fortune(), "Hello")


class ResolveTopic(unittest.TestCase):
    def test_empty_words_mean_any(self):
        for raw in ("", "any", "ALL", "none", None):
            with self.subTest(raw=raw):
                self.assertFalse(Q.resolve_topic(raw).active)

    def test_known_topic(self):
        t = Q.resolve_topic("Technology")
        self.assertTrue(t.active)
        self.assertEqual(t.name, "technology")

    def test_alias_gives_the_same_topic(self):
        t = Q.resolve_topic("technology")
        for name, info in Q.TOPICS.items():
            if name == "technology" and info["aliases"]:
                self.assertEqual(Q.resolve_topic(info["aliases"][0]).name, "technology")

    def test_unknown_word_is_still_a_topic(self):
        t = Q.resolve_topic("chess")
        self.assertEqual(t.name, "chess")
        self.assertTrue(t.matches_text("A game of Chess"))
        self.assertTrue(t.matches_file("chess"))

    def test_auto_uses_the_page_text(self):
        t = Q.resolve_topic("auto", "categories: [technology]")
        self.assertEqual(t.name, "technology")

    def test_auto_without_a_match_is_no_topic(self):
        self.assertFalse(Q.resolve_topic("auto", "zzz qqq").active)

    def test_inactive_topic_matches_nothing(self):
        t = Q.Topic()
        self.assertFalse(t.matches_text("anything"))
        self.assertFalse(t.matches_file("anything"))


if __name__ == "__main__":
    unittest.main()


class DailyQuote(unittest.TestCase):
    """The page-less quote used by the dashboard (util.select_quote)."""

    def setUp(self):
        self._saved = dict(Q.SOURCES)

    def tearDown(self):
        Q.SOURCES.clear()
        Q.SOURCES.update(self._saved)

    def _fake(self, *quotes):
        Q.SOURCES.clear()
        Q.SOURCES["fake"] = lambda cfg, topic, notes: list(quotes)

    def _quote(self, text="A perfectly fine quote about life.", author="Someone"):
        return Q.Quote(text=text, author=author, source="fake")

    def test_returns_one_acceptable_quote(self):
        good = self._quote()
        self._fake(good, self._quote(text="x", author="Too short"))
        quote, notes = Q.pick_daily_quote(sources=("fake",))
        self.assertIs(quote, good)
        self.assertEqual(Q.daily_quote(sources=("fake",)), good)

    def test_no_quote_when_nothing_is_acceptable(self):
        self._fake(self._quote(author=""))
        quote, _ = Q.pick_daily_quote(sources=("fake",))
        self.assertIsNone(quote)

    def test_unknown_source_is_reported_not_raised(self):
        self._fake()
        quote, notes = Q.pick_daily_quote(sources=("nope",))
        self.assertIsNone(quote)
        self.assertTrue(any("nope" in message for _, message in notes))

    def test_failing_source_does_not_break(self):
        def boom(cfg, topic, notes):
            raise RuntimeError("down")

        Q.SOURCES.clear()
        Q.SOURCES["boom"] = boom
        Q.SOURCES["fake"] = lambda cfg, topic, notes: [self._quote()]
        quote, notes = Q.pick_daily_quote(sources=("boom", "fake"))
        self.assertIsNotNone(quote)
        self.assertTrue(any("boom" in message for _, message in notes))


class UtilSelectQuote(unittest.TestCase):
    def test_util_no_longer_depends_on_the_quote_package(self):
        from pathlib import Path

        source = (Path(__file__).resolve().parent.parent / "util.py").read_text()
        self.assertNotIn("from quote import", source)
        self.assertNotIn("import quote\n", source)

    def test_select_quote_prints_text_and_author(self):
        import io
        from contextlib import redirect_stdout

        import util

        saved = Q.pick_daily_quote
        Q.pick_daily_quote = lambda *a, **k: (Q.Quote(text="Hello quote", author="Me", source="fake"), [])
        try:
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertIsNone(util.select_quote())
        finally:
            Q.pick_daily_quote = saved
        self.assertIn("Hello quote", out.getvalue())
        self.assertIn("Me", out.getvalue())

    def test_select_quote_without_quotes_prints_a_notice(self):
        import io
        from contextlib import redirect_stdout

        import util

        saved = Q.pick_daily_quote
        Q.pick_daily_quote = lambda *a, **k: (None, [("warn", "all sources failed")])
        try:
            out = io.StringIO()
            with redirect_stdout(out):
                util.select_quote()
        finally:
            Q.pick_daily_quote = saved
        self.assertIn("No quote today", out.getvalue())
