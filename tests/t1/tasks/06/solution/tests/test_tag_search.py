import unittest

from src.service import NoteService
from src.store import NoteStore


class NoteTagSearchTests(unittest.TestCase):
    def setUp(self):
        self.service = NoteService(NoteStore())
        self.first = self.service.create("1", "one", "", [" Work ", "Home"])
        self.second = self.service.create("2", "two", "", ["work"])
        self.third = self.service.create("3", "three", "")

    def test_all_and_any_are_case_insensitive_and_keep_store_order(self):
        self.assertEqual(self.service.search_tags(["WORK", "home"]), [self.first])
        self.assertEqual(self.service.search_tags(["work", "home"], "any"), [self.first, self.second])

    def test_empty_query_and_empty_tags(self):
        self.assertEqual(self.service.search_tags([]), [])
        self.assertEqual(self.third.tags, [])
        self.assertEqual(self.service.search_tags([" "]), [])

    def test_unknown_match_is_rejected(self):
        with self.assertRaises(ValueError):
            self.service.search_tags(["work"], "none")
