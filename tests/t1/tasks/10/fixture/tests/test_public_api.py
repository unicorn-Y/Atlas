import unittest

from src.contacts import contact_card
from src.directory import directory_entry
from src.export import export_row
from src.models import User
from src.profile import profile_label


class PublicFormattingTests(unittest.TestCase):
    def test_public_helpers_keep_their_output(self):
        user = User("Ada", "London")
        expected = "Ada — London"
        self.assertEqual(contact_card(user), expected)
        self.assertEqual(directory_entry(user), expected)
        self.assertEqual(export_row(user), expected)
        self.assertEqual(profile_label(user), expected)


if __name__ == "__main__":
    unittest.main()
