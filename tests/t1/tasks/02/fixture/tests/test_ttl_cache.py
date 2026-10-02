import unittest

from ttl_cache import TTLCache


class TTLCacheTests(unittest.TestCase):
    def setUp(self):
        self.now = 10.0
        self.cache = TTLCache(5.0, lambda: self.now)

    def test_hit_before_expiration_does_not_reload(self):
        calls = []
        first = self.cache.get_or_load("a", lambda: calls.append(1) or "first")
        self.now = 14.999
        second = self.cache.get_or_load("a", lambda: calls.append(2) or "second")
        self.assertEqual((first, second, calls), ("first", "first", [1]))

    def test_exact_expiration_time_is_expired(self):
        calls = []
        self.cache.get_or_load("a", lambda: calls.append(1) or "first")
        self.now = 15.0
        value = self.cache.get_or_load("a", lambda: calls.append(2) or "second")
        self.assertEqual((value, calls), ("second", [1, 2]))

    def test_keys_expire_independently(self):
        self.cache.get_or_load("a", lambda: "A")
        self.now = 14.0
        self.cache.get_or_load("b", lambda: "B")
        self.now = 15.0
        self.assertEqual(self.cache.get_or_load("a", lambda: "new A"), "new A")
        self.assertEqual(self.cache.get_or_load("b", lambda: "new B"), "B")


if __name__ == "__main__":
    unittest.main()
