import unittest

from src.catalog import Catalog
from src.item import Item


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = Catalog()
        self.alpha = Item("a", "Alpha")
        self.catalog.add(self.alpha)

    def test_get_and_all(self):
        self.assertEqual(self.catalog.get("a"), self.alpha)
        self.assertEqual(self.catalog.all(), [self.alpha])

    def test_add_replaces_same_id(self):
        replacement = Item("a", "Again")
        self.catalog.add(replacement)
        self.assertEqual(self.catalog.get("a"), replacement)
        self.assertEqual(len(self.catalog.all()), 1)


if __name__ == "__main__":
    unittest.main()
