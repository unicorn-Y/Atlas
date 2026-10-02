from src.item import Item


class Catalog:
    def __init__(self):
        self._items = {}

    def add(self, item: Item) -> None:
        self._items[item.id] = item

    def get(self, item_id: str) -> Item | None:
        return self._items.get(item_id)

    def all(self) -> list[Item]:
        return list(self._items.values())

    def search_prefix(self, prefix: str, limit: int | None = None) -> list[Item]:
        if limit is not None and limit < 0:
            raise ValueError("limit must be non-negative")
        needle = prefix.casefold()
        matches = [item for item in self._items.values() if item.name.casefold().startswith(needle)]
        matches.sort(key=lambda item: (item.name.casefold(), item.id))
        return matches if limit is None else matches[:limit]
