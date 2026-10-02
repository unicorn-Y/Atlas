import unittest

from rounding import round_to_cents


class RoundToCentsTests(unittest.TestCase):
    def test_ordinary_values(self):
        self.assertEqual(round_to_cents(12.34), 12.34)
        self.assertEqual(round_to_cents(-12.34), -12.34)

    def test_half_cent_rounds_away_from_zero(self):
        self.assertEqual(round_to_cents(1.005), 1.01)
        self.assertEqual(round_to_cents(-1.005), -1.01)

    def test_values_just_below_half_cent(self):
        self.assertEqual(round_to_cents(2.004), 2.00)
        self.assertEqual(round_to_cents(-2.004), -2.00)


if __name__ == "__main__":
    unittest.main()
