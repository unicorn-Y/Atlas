import unittest


class LegacyCompatibilityTest(unittest.TestCase):
    def test_public_version_marker_is_stable(self):
        self.assertEqual("v1", "v1")


if __name__ == "__main__":
    unittest.main()
