import unittest

from src.service import NoteService
from src.store import NoteStore


class NoteServiceTests(unittest.TestCase):
    def test_create_and_list(self):
        service = NoteService(NoteStore())
        note = service.create("n1", "Title", "Body")
        self.assertEqual(service.list_notes(), [note])
        self.assertEqual((note.id, note.title, note.body), ("n1", "Title", "Body"))


if __name__ == "__main__":
    unittest.main()
