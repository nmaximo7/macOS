"""content_latex: the LaTeX fixer. New pieces come back between the marks S ... E."""

import unittest

import content_latex as L


def plain(text):
    """Remove the 'this is new' marks, to compare only the resulting text."""
    return L._strip(text)


class FixMath(unittest.TestCase):
    def test_sup_tag_becomes_superscript(self):
        self.assertEqual(plain(L.fix_math("x<sup>2</sup>")), "x^{2}")

    def test_changed_pieces_are_marked(self):
        self.assertEqual(L.fix_math("x<sup>2</sup>"), "x" + L.S + "^{2}" + L.E)

    def test_fraction_tags(self):
        self.assertEqual(plain(L.fix_math("<sup>1</sup>/<sub>2</sub>")), r"\frac{1}{2}")

    def test_function_names_get_a_backslash(self):
        self.assertEqual(plain(L.fix_math("sin x")), r"\sin x")

    def test_already_correct_math_is_untouched(self):
        for ok in (r"\sin x", "plain", "a_bc", r"\frac{1}{2}"):
            with self.subTest(ok=ok):
                self.assertEqual(L.fix_math(ok), ok)

    def test_greek_letters_become_commands(self):
        self.assertEqual(plain(L.fix_math("α + β")), r"\alpha + \beta")

    def test_multi_digit_exponent_gets_braces(self):
        self.assertEqual(plain(L.fix_math("x^23")), "x^{23}")

    def test_idempotent(self):
        """Fixing the result again must not change it (no endless 'fixes')."""
        for src in ("x<sup>2</sup>", "sin x", "α + β", "x^23"):
            with self.subTest(src=src):
                once = plain(L.fix_math(src))
                self.assertEqual(plain(L.fix_math(once)), once)


class ConvertLine(unittest.TestCase):
    def test_prose_superscript_is_wrapped_in_dollars(self):
        marked, display = L._convert_line("The area is x<sup>2</sup> here.", False)
        self.assertEqual(plain(marked), "The area is $x^2$ here.")
        self.assertFalse(display)

    def test_plain_line_is_unchanged(self):
        self.assertEqual(L._convert_line("nothing here", False), ("nothing here", False))

    def test_open_display_block_is_reported(self):
        _marked, display = L._convert_line("$$ x<sup>2</sup>", False)
        self.assertTrue(display)

    def test_display_block_closes(self):
        _marked, display = L._convert_line("y $$ after", True)
        self.assertFalse(display)


if __name__ == "__main__":
    unittest.main()
