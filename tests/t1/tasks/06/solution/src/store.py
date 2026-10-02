from src.models import Note


class NoteStore:
    def __init__(self):
        self._notes = []

    def add(self, note: Note) -> None:
        self._notes.append(note)

    def list_all(self) -> list[Note]:
        return list(self._notes)

    def find_by_tags(self, tags: set[str], match: str) -> list[Note]:
        if not tags:
            return []
        if match == "all":
            return [note for note in self._notes if tags.issubset({tag.casefold() for tag in note.tags})]
        return [note for note in self._notes if tags.intersection({tag.casefold() for tag in note.tags})]
