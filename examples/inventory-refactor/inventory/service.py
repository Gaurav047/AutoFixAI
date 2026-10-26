from .models import OutOfStock, Product
from .pricing import bulk_price


class InventoryService:
    def __init__(self):
        self._products: dict[str, Product] = {}

    def add_product(self, product: Product) -> None:
        self._products[product.sku] = product

    def get(self, sku: str) -> Product:
        return self._products[sku]

    def restock(self, sku: str, amount: int) -> int:
        product = self.get(sku)
        product.qty += amount
        return product.qty

    def quote(self, sku: str, quantity: int) -> float:
        product = self.get(sku)
        return bulk_price(product.unit_price, quantity)

    def place_order(self, sku: str, quantity: int) -> float:
        product = self.get(sku)
        if quantity > product.stock:
            raise OutOfStock(sku, quantity, product.stock)
        price = self.quote(sku, quantity)
        product.stock -= quantity
        return price
