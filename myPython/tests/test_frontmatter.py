"""content_frontmatter: parsing, cleaning the model's answer and building the proposal."""

import unittest
from types import SimpleNamespace
from unittest import mock

import content_frontmatter as F


class SplitAndParse(unittest.TestCase):
    def test_split_page(self):
        self.assertEqual(F._split_page("---\na: 1\n---\nbody"), ("a: 1", "body"))

    def test_no_front_matter(self):
        self.assertEqual(F._split_page("just text"), ("", "just text"))

    def test_unclosed_front_matter_is_ignored(self):
        text = "---\na: 1\nbody"
        self.assertEqual(F._split_page(text), ("", text))

    def test_bom_is_tolerated(self):
        self.assertEqual(F._split_page("﻿---\na: 1\n---\nx")[0], "a: 1")

    def test_parse_blocks_keeps_lists_together(self):
        blocks = F._parse_blocks('title: "T"\ncategories:\n- a\n- b\n\nweight: 3')
        self.assertEqual(list(blocks), ["title", "categories", "weight"])
        self.assertEqual(blocks["categories"], ["categories:", "- a", "- b"])

    def test_block_value(self):
        self.assertEqual(F._block_value(['title: "Hello  there"']), "Hello there")
        self.assertEqual(F._block_value(["tags: [a, 'b']"]), ("a", "b"))
        self.assertEqual(F._block_value(["categories:", '- "a"', "- b"]), ("a", "b"))


class Cleaning(unittest.TestCase):
    def test_clean_text(self):
        self.assertEqual(F._clean_text('  "Hello\n  world"  '), "Hello world")

    def test_title_loses_final_dot_and_cannot_be_empty(self):
        self.assertEqual(F._clean_title("A title."), "A title")
        with self.assertRaises(ValueError):
            F._clean_title("  ")

    def test_keywords_from_list_or_string(self):
        self.assertEqual(F._clean_keywords(["Alpha", "beta", "ALPHA"]), "alpha, beta")
        self.assertEqual(F._clean_keywords("one, two\nthree"), "one, two, three")

    def test_keywords_keep_camel_case_and_drop_yaml_characters(self):
        self.assertEqual(F._clean_keywords(["macOS", "iPhone", "a:b", "#tag"]), "macOS, iPhone, ab, tag")

    def test_keywords_are_limited(self):
        many = [f"k{i}" for i in range(100)]
        self.assertEqual(len(F._clean_keywords(many).split(", ")), F.MAX_KEYWORDS)

    def test_no_keywords_is_an_error(self):
        for bad in ([], "", None, ["", " "]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                F._clean_keywords(bad)

    def test_categories_use_the_sites_spelling(self):
        self.assertEqual(F._clean_categories(["linux", "Maths"], ("Linux", "maths")), ["Linux", "maths"])

    def test_categories_unique_and_limited(self):
        got = F._clean_categories(["a", "A", "b", "c", "d", "e"], ())
        self.assertEqual(got, ["a", "b", "c", "d"][: F.MAX_CATEGORIES])

    def test_no_categories_is_an_error(self):
        with self.assertRaises(ValueError):
            F._clean_categories([], ())

    def test_short_description_is_kept(self):
        self.assertEqual(F._clean_description("Short one."), "Short one.")

    def test_long_description_is_cut_cleanly(self):
        text = ("This is a sentence. " * 30).strip()
        out = F._clean_description(text)
        self.assertLessEqual(len(out), 320)
        self.assertTrue(out.endswith("."))

    def test_long_description_without_sentences_ends_with_a_dot(self):
        out = F._clean_description("word " * 100)
        self.assertLessEqual(len(out), 321)
        self.assertTrue(out.endswith("."))


class YamlText(unittest.TestCase):
    def test_quote_escapes(self):
        self.assertEqual(F._quote('say "hi" \\'), '"say \\"hi\\" \\\\"')

    def test_scalar_plain_when_safe(self):
        self.assertEqual(F._scalar("Hello world"), "Hello world")

    def test_scalar_quoted_when_unsafe(self):
        for text in ("yes", "123", "a: b", "ends:", "x #y", "- item", "", "@home"):
            with self.subTest(text=text):
                self.assertTrue(F._scalar(text).startswith('"'))

    def test_comparable_ignores_format(self):
        self.assertEqual(F._comparable("a, B"), F._comparable(["a", "b"]))


class BuildBlocks(unittest.TestCase):
    AI = {"keywords": ["k1"], "categories": ["c1"], "title": "T", "description": "D."}

    def build(self, existing, author="", image=""):
        cfg = SimpleNamespace(author=author, featured_image=image)
        with mock.patch.object(F, "get_settings", return_value=cfg):
            return F._build_blocks(existing, self.AI, ())

    def keys(self, blocks):
        return [b[0] for b in blocks]

    def test_no_author_configured_and_none_on_page(self):
        self.assertNotIn("author", self.keys(self.build({})))

    def test_no_author_configured_keeps_the_pages_own(self):
        blocks = dict((k, (lines, changed)) for k, lines, changed in self.build({"author": ["author: Me"]}))
        self.assertEqual(blocks["author"], (["author: Me"], False))

    def test_author_configured_is_proposed(self):
        blocks = dict((k, (lines, changed)) for k, lines, changed in self.build({}, author="Ann"))
        self.assertEqual(blocks["author"], (["author: Ann"], True))

    def test_same_author_is_not_a_change(self):
        blocks = dict((k, changed) for k, _l, changed in self.build({"author": ["author: Ann"]}, author="Ann"))
        self.assertFalse(blocks["author"])

    def test_featured_image_only_when_configured(self):
        self.assertNotIn("featured_image", self.keys(self.build({})))
        got = dict((k, lines) for k, lines, _c in self.build({}, image="/x.jpg"))
        self.assertEqual(got["featured_image"], ["featured_image: /x.jpg"])

    def test_pages_own_featured_image_wins(self):
        got = dict((k, lines) for k, lines, _c in self.build({"featured_image": ["featured_image: /mine.jpg"]}, image="/x.jpg"))
        self.assertEqual(got["featured_image"], ["featured_image: /mine.jpg"])

    def test_extras_sit_before_description(self):
        keys = self.keys(self.build({}, image="/x.jpg"))
        self.assertLess(keys.index("featured_image"), keys.index("description"))
        self.assertLess(keys.index("weight"), keys.index("description"))

    def test_unknown_keys_are_kept_at_the_end(self):
        blocks = self.build({"draft": ["draft: true"]})
        self.assertEqual(blocks[-1], ("draft", ["draft: true"], False))


if __name__ == "__main__":
    unittest.main()
