import unittest

from src.catalog import Catalog
from src.item import Item


class CatalogSearchTests(unittest.TestCase):
    def setUp(self):
        self.catalog = Catalog()
        for item in [Item("z", "beta"), Item("b", "BETA"), Item("a", "Berry"), Item("c", "Alpha")]:
            self.catalog.add(item)

    def test_prefix_is_case_insensitive_and_stably_sorted(self):
        self.assertEqual([x.id for x in self.catalog.search_prefix("Be")], ["a", "b", "z"])

    def test_empty_prefix_and_limits(self):
        self.assertEqual([x.id for x in self.catalog.search_prefix("")], ["c", "a", "b", "z"])
        self.assertEqual([x.id for x in self.catalog.search_prefix("b", 1)], ["a"])
        self.assertEqual(self.catalog.search_prefix("b", 0), [])

    def test_negative_limit_is_rejected(self):
        with self.assertRaises(ValueError):
            self.catalog.search_prefix("b", -1)
