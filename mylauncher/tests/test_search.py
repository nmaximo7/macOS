"""mysearch.py: matching, ranking and autocomplete."""

import unittest

import support  # noqa: F401  (puts cli/ on the import path)
from mysearch import (
    SCORE_EXACT,
    SCORE_FUZZY,
    SCORE_INSIDE,
    SCORE_STARTS,
    SCORE_WORD,
    complete,
    normalize,
    rank,
    score_text,
)
from mytypes import Item

SHUTDOWN = Item("cmd:shutdown", "Shutdown", "command", "shutdown", keywords=("shut down", "power off"), confirm=True)


def app(name):
    return Item(f"app:{name}", f"Run {name}", "app", "open_app", target=f"/Applications/{name}.app")


ITEMS = [SHUTDOWN, app("Obsidian"), app("Safari"), app("Visual Studio Code"), app("Café"), app("Zen")]


def titles(matches):
    return [m.item.title for m in matches]


class Normalize(unittest.TestCase):
    def test_lower_case_spaces_and_accents(self):
        self.assertEqual(normalize("  Café   OBS "), "cafe obs")

    def test_accents_can_be_kept(self):
        self.assertEqual(normalize("Café", ignore_accents=False), "café")


class Scores(unittest.TestCase):
    def test_each_rule(self):
        self.assertEqual(score_text("shutdown", "shutdown"), SCORE_EXACT)
        self.assertEqual(score_text("shut", "shutdown"), SCORE_STARTS)
        self.assertEqual(score_text("obs", "run obsidian"), SCORE_WORD)
        self.assertEqual(score_text("sidi", "run obsidian"), SCORE_INSIDE)
        self.assertEqual(score_text("rsfr", "run safari"), SCORE_FUZZY)
        self.assertEqual(score_text("xyz", "run safari"), 0)

    def test_the_rules_are_in_order(self):
        self.assertGreater(SCORE_EXACT, SCORE_STARTS)
        self.assertGreater(SCORE_STARTS, SCORE_WORD)
        self.assertGreater(SCORE_WORD, SCORE_INSIDE)
        self.assertGreater(SCORE_INSIDE, SCORE_FUZZY)
        self.assertGreater(SCORE_FUZZY, 0)

    def test_fuzzy_can_be_turned_off(self):
        self.assertEqual(score_text("sfr", "run safari", fuzzy=False), 0)

    def test_fuzzy_needs_the_right_order(self):
        self.assertEqual(score_text("frs", "run safari", fuzzy=True), 0)

    def test_empty_query_matches_everything_a_little(self):
        self.assertEqual(score_text("", "anything"), 1)


class Ranking(unittest.TestCase):
    def test_lower_and_upper_case_are_the_same(self):
        self.assertEqual(titles(rank(ITEMS, "OBS")), titles(rank(ITEMS, "obs")))
        self.assertEqual(titles(rank(ITEMS, "obs")), ["Run Obsidian"])

    def test_run_prefix_finds_apps(self):
        self.assertEqual(titles(rank(ITEMS, "run obs")), ["Run Obsidian"])

    def test_word_in_the_middle_of_a_title(self):
        self.assertEqual(titles(rank(ITEMS, "code")), ["Run Visual Studio Code"])
        self.assertIn("Run Visual Studio Code", titles(rank(ITEMS, "studio")))

    def test_keywords_find_the_command(self):
        self.assertEqual(titles(rank(ITEMS, "power")), ["Shutdown"])
        self.assertEqual(titles(rank(ITEMS, "shut down")), ["Shutdown"])

    def test_accents_are_ignored_by_default(self):
        self.assertEqual(titles(rank(ITEMS, "cafe")), ["Run Café"])
        self.assertEqual(titles(rank(ITEMS, "cafe", ignore_accents=False, fuzzy=False)), [])

    def test_best_score_first(self):
        # "s": Shutdown starts with it (80); apps only have a WORD starting with it (60): Safari, Studio
        result = rank(ITEMS, "s", fuzzy=False)
        self.assertEqual(result[0].item.title, "Shutdown")
        self.assertEqual(result[0].score, SCORE_STARTS)

    def test_ties_put_commands_first_then_alphabetical(self):
        everything = rank(ITEMS, "")
        self.assertEqual(everything[0].item.title, "Shutdown")
        self.assertEqual(titles(everything)[1:], sorted(titles(everything)[1:], key=normalize))

    def test_limit(self):
        self.assertEqual(len(rank(ITEMS, "", limit=3)), 3)

    def test_no_match(self):
        self.assertEqual(rank(ITEMS, "qqq"), [])

    def test_whitespace_only_query_is_empty(self):
        self.assertEqual(len(rank(ITEMS, "   ")), len(ITEMS))


class Complete(unittest.TestCase):
    def test_completion_is_the_best_title_in_lower_case(self):
        self.assertEqual(complete("obs", rank(ITEMS, "obs")), "run obsidian")
        self.assertEqual(complete("shu", rank(ITEMS, "shu")), "shutdown")

    def test_no_match_keeps_the_text(self):
        self.assertEqual(complete("qqq", []), "qqq")


if __name__ == "__main__":
    unittest.main()
