from src.models import Product
from src.store import InventoryStore


class InventoryService:
    def __init__(self, store: InventoryStore):
        self._store = store

    def add_product(self, sku: str, name: str, quantity: int) -> Product:
        product = Product(sku, name, quantity)
        self._store.add(product)
        return product

    def get_product(self, sku: str) -> Product | None:
        return self._store.get(sku)

    def adjust_stock(self, sku: str, delta: int) -> Product:
        current = self._store.get(sku)
        if current is None:
            raise KeyError(sku)
        quantity = current.quantity + delta
        if quantity < 0:
            raise ValueError("stock cannot become negative")
        updated = Product(current.sku, current.name, quantity)
        self._store.replace(updated)
        return updated
