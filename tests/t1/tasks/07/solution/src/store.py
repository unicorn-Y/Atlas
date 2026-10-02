from src.models import Product


class InventoryStore:
    def __init__(self):
        self._products = {}

    def add(self, product: Product) -> None:
        self._products[product.sku] = product

    def get(self, sku: str) -> Product | None:
        return self._products.get(sku)

    def replace(self, product: Product) -> None:
        if product.sku not in self._products:
            raise KeyError(product.sku)
        self._products[product.sku] = product
