"""myhistory.py: the memory of what you use."""

import json
import unittest

import support
from myhistory import History


class Memory(support.TempDirCase):
    def history(self, enabled=True):
        return History(self.tmp / "sub" / "usage.json", enabled)

    def test_starts_empty(self):
        self.assertEqual(self.history().counts(), {})

    def test_record_counts_and_creates_folders(self):
        h = self.history()
        self.assertTrue(h.record("app:Obsidian"))
        h.record("app:Obsidian")
        h.record("cmd:shutdown")
        self.assertEqual(h.counts(), {"app:Obsidian": 2, "cmd:shutdown": 1})
        self.assertEqual(json.loads(h.path.read_text())["version"], 1)

    def test_top_is_sorted_most_used_first(self):
        h = self.history()
        for item, times in (("a", 1), ("b", 3), ("c", 3)):
            for _ in range(times):
                h.record(item)
        self.assertEqual(h.top(), [("b", 3), ("c", 3), ("a", 1)])
        self.assertEqual(h.top(1), [("b", 3)])

    def test_disabled_does_nothing(self):
        h = self.history(enabled=False)
        self.assertFalse(h.record("x"))
        self.assertFalse(h.path.exists())
        self.assertEqual(h.counts(), {})

    def test_damaged_files_mean_no_history(self):
        h = self.history()
        h.path.parent.mkdir(parents=True)
        cases = [
            ("not json", {}),
            ("[]", {}),
            ('{"counts": 5}', {}),
            ('{"counts": {"a": "x", "b": -1, "c": 2}}', {"c": 2}),  # only valid entries survive
            ("", {}),
        ]
        for text, expected in cases:
            h.path.write_text(text)
            with self.subTest(text=text):
                self.assertEqual(h.counts(), expected)

    def test_a_damaged_file_is_repaired_by_the_next_record(self):
        h = self.history()
        h.path.parent.mkdir(parents=True)
        h.path.write_text("garbage")
        h.record("a")
        self.assertEqual(h.counts(), {"a": 1})

    def test_unwritable_location_is_ignored(self):
        blocker = self.tmp / "file"
        blocker.write_text("I am a file, not a folder")
        self.assertFalse(History(blocker / "usage.json").record("a"))  # no exception

    def test_clear(self):
        h = self.history()
        h.record("a")
        h.clear()
        self.assertEqual(h.counts(), {})
        h.clear()  # clearing twice is fine

    def test_no_temporary_file_is_left_behind(self):
        h = self.history()
        h.record("a")
        self.assertEqual([p.name for p in h.path.parent.iterdir()], ["usage.json"])


if __name__ == "__main__":
    unittest.main()
