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
