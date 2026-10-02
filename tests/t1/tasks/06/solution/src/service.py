from src.models import Note
from src.store import NoteStore


class NoteService:
    def __init__(self, store: NoteStore):
        self._store = store

    def create(self, note_id: str, title: str, body: str, tags: list[str] | None = None) -> Note:
        clean_tags = [tag.strip() for tag in (tags or []) if tag.strip()]
        note = Note(note_id, title, body, clean_tags)
        self._store.add(note)
        return note

    def list_notes(self) -> list[Note]:
        return self._store.list_all()

    def search_tags(self, tags: list[str], match: str = "all") -> list[Note]:
        if match not in {"all", "any"}:
            raise ValueError("match must be 'all' or 'any'")
        clean_tags = {tag.strip().casefold() for tag in tags if tag.strip()}
        return self._store.find_by_tags(clean_tags, match)
