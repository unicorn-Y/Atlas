from src.models import Note


class NoteStore:
    def __init__(self):
        self._notes = []

    def add(self, note: Note) -> None:
        self._notes.append(note)

    def list_all(self) -> list[Note]:
        return list(self._notes)
