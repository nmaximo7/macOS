"""myapps.py: finding the applications."""

import unittest

import support
from myapps import find_apps


class FindApps(support.TempDirCase):
    def test_finds_apps_sorted_by_name(self):
        folder = self.make_apps("A", "Zen", "Obsidian", "safari")
        self.assertEqual([n for n, _ in find_apps([folder])], ["Obsidian", "safari", "Zen"])

    def test_path_is_the_app_folder(self):
        folder = self.make_apps("A", "Obsidian")
        name, path = find_apps([folder])[0]
        self.assertEqual(path, folder / "Obsidian.app")

    def test_ignores_files_and_other_folders(self):
        folder = self.make_apps("A", "Real")
        (folder / "fake.app").write_text("a file, not an app")
        (folder / "Utilities").mkdir()
        (folder / "notes.txt").write_text("x")
        self.assertEqual([n for n, _ in find_apps([folder])], ["Real"])

    def test_missing_folder_is_skipped(self):
        folder = self.make_apps("A", "Real")
        self.assertEqual(len(find_apps([self.tmp / "nope", folder])), 1)

    def test_first_folder_wins_for_the_same_name(self):
        first = self.make_apps("first", "Same")
        second = self.make_apps("second", "same", "Other")
        apps = dict(find_apps([first, second]))
        self.assertEqual(apps["Same"], first / "Same.app")
        self.assertEqual(sorted(apps), ["Other", "Same"])

    def test_exclude_ignores_case(self):
        folder = self.make_apps("A", "Boot Camp Assistant", "Keep")
        self.assertEqual([n for n, _ in find_apps([folder], exclude=("boot camp assistant",))], ["Keep"])

    def test_no_folders(self):
        self.assertEqual(find_apps([]), [])


if __name__ == "__main__":
    unittest.main()
