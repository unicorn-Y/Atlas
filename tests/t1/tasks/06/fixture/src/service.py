from src.models import Note
from src.store import NoteStore


class NoteService:
    def __init__(self, store: NoteStore):
        self._store = store

    def create(self, note_id: str, title: str, body: str) -> Note:
        note = Note(note_id, title, body)
        self._store.add(note)
        return note

    def list_notes(self) -> list[Note]:
        return self._store.list_all()
