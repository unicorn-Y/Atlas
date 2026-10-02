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
