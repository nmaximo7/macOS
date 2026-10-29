"""myconfig: building Settings from environment variables (no .env file is read)."""

import os
import unittest
from pathlib import Path
from unittest import mock

import myconfig as C


def load(**env):
    """load_settings() with ONLY these variables set."""
    with mock.patch.dict(os.environ, env, clear=True):
        return C.load_settings()


class Helpers(unittest.TestCase):
    def test_split_list(self):
        self.assertEqual(C._split_list("a b,c,,d "), ("a", "b", "c", "d"))
        self.assertEqual(C._split_list(""), ())

    def test_normalize_server(self):
        self.assertEqual(C._normalize_server("192.168.1.46:1313"), "http://192.168.1.46:1313")
        self.assertEqual(C._normalize_server('"https://x.org/"'), "https://x.org")
        self.assertEqual(C._normalize_server("  "), "")


class Defaults(unittest.TestCase):
    def test_empty_environment(self):
        s = load()
        self.assertEqual(s.model_query, C.DEFAULT_MODEL)
        self.assertEqual(s.base_url, C.DEFAULT_HOST)
        self.assertEqual(s.timeout, C.DEFAULT_TIMEOUT)
        self.assertIsNone(s.num_ctx)
        self.assertEqual(s.hugo_server, "")
        self.assertIsNone(s.hugo_root)
        self.assertIsNone(s.fortunes_path)
        self.assertEqual(s.models_newcontent, ())
        self.assertEqual(s.rss_feed_urls, ())
        self.assertEqual(s.number_quotes, C.DEFAULT_NUMBER_QUOTES)
        self.assertEqual(s.quote_sources, C.DEFAULT_QUOTE_SOURCES)
        self.assertEqual(s.weather_lang, C.DEFAULT_WEATHER_LANG)
        self.assertEqual(s.stock_tickers, C.DEFAULT_STOCK_TICKERS)
        self.assertEqual((s.author, s.featured_image, s.weather_city, s.topic), ("", "", "", ""))

    def test_settings_are_read_only(self):
        with self.assertRaises(Exception):
            load().author = "x"


class Values(unittest.TestCase):
    def test_a_real_looking_configuration(self):
        s = load(
            HUGO_SERVER="192.168.1.46:1313",
            HUGO_ROOT="/site",
            MODELS_NEWCONTENT="a:1b  c:2b",
            TOPIC=' "Technology" ',
            NUMBER_QUOTES="7",
            QUOTE_SOURCES="File,Fortune zenquotes",
            RSS_FEED_URLS="https://a.org/feed https://b.org/rss",
            WEATHER_CITY=" Malaga ",
            WEATHER_LANG="ES",
            STOCK_TICKERS="aapl, msft",
            AUTHOR='"Ann, Bob"',
        )
        self.assertEqual(s.hugo_server, "http://192.168.1.46:1313")
        self.assertEqual(s.hugo_root, Path("/site"))
        self.assertEqual(s.topic, "technology")
        self.assertEqual(s.number_quotes, 7)
        self.assertEqual(s.quote_sources, ("file", "fortune", "zenquotes"))
        self.assertEqual(s.rss_feed_urls, ("https://a.org/feed", "https://b.org/rss"))
        self.assertEqual((s.weather_city, s.weather_lang), ("Malaga", "es"))
        self.assertEqual(s.stock_tickers, ("AAPL", "MSFT"))
        self.assertEqual(s.author, "Ann, Bob")
        self.assertEqual(s.models_newcontent, ("a:1b", "c:2b"))

    def test_tilde_is_expanded(self):
        self.assertEqual(load(FORTUNES_PATH="~/f").fortunes_path, Path("~/f").expanduser())

    def test_number_quotes_is_at_least_one(self):
        self.assertEqual(load(NUMBER_QUOTES="0").number_quotes, 1)
        self.assertEqual(load(NUMBER_QUOTES="-5").number_quotes, 1)

    def test_timeout_and_context(self):
        s = load(OLLAMA_TIMEOUT="30.5", OLLAMA_NUM_CTX="32768")
        self.assertEqual((s.timeout, s.num_ctx), (30.5, 32768))

    def test_blank_numbers_use_the_default(self):
        s = load(OLLAMA_TIMEOUT="  ", NUMBER_QUOTES="")
        self.assertEqual((s.timeout, s.number_quotes), (C.DEFAULT_TIMEOUT, C.DEFAULT_NUMBER_QUOTES))

    def test_invalid_number_names_the_variable(self):
        for name in ("OLLAMA_TIMEOUT", "OLLAMA_NUM_CTX", "NUMBER_QUOTES"):
            with self.subTest(name=name), self.assertRaises(ValueError) as ctx:
                load(**{name: "many"})
            self.assertIn(name, str(ctx.exception))

    def test_feed_url_with_comma_is_not_split(self):
        s = load(RSS_FEED_URLS="https://a.org/feed?x=1,2")
        self.assertEqual(s.rss_feed_urls, ("https://a.org/feed?x=1,2",))


if __name__ == "__main__":
    unittest.main()
