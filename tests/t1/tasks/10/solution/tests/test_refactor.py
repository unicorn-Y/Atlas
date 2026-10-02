import unittest

from src.models import User
from src.presentation import render_user


class PresentationRefactorTests(unittest.TestCase):
    def test_render_user_preserves_public_format(self):
        self.assertEqual(render_user(User("Ada", "London")), "Ada — London")
