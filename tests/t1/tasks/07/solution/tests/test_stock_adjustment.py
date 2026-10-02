import unittest

from src.service import InventoryService
from src.store import InventoryStore


class StockAdjustmentTests(unittest.TestCase):
    def setUp(self):
        self.service = InventoryService(InventoryStore())
        self.original = self.service.add_product("A-1", "Widget", 4)

    def test_positive_negative_and_zero_adjustments(self):
        self.assertEqual(self.service.adjust_stock("A-1", 3).quantity, 7)
        self.assertEqual(self.service.adjust_stock("A-1", -2).quantity, 5)
        self.assertEqual(self.service.adjust_stock("A-1", 0).quantity, 5)

    def test_invalid_adjustment_keeps_previous_state(self):
        with self.assertRaises(ValueError):
            self.service.adjust_stock("A-1", -5)
        self.assertEqual(self.service.get_product("A-1"), self.original)

    def test_unknown_sku_raises(self):
        with self.assertRaises(KeyError):
            self.service.adjust_stock("missing", 1)
