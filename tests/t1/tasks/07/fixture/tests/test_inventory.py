import unittest

from src.service import InventoryService
from src.store import InventoryStore


class InventoryTests(unittest.TestCase):
    def test_add_and_get_product(self):
        service = InventoryService(InventoryStore())
        product = service.add_product("A-1", "Widget", 4)
        self.assertEqual(service.get_product("A-1"), product)
        self.assertIsNone(service.get_product("missing"))


if __name__ == "__main__":
    unittest.main()
