from dataclasses import dataclass


@dataclass(slots=True)
class Product:
    sku: str
    name: str
    unit_price: float
    stock: int = 0  # renamed from `qty` in v2.0


class OutOfStock(Exception):
    def __init__(self, sku: str, requested: int, available: int):
        super().__init__(f"{sku}: requested {requested}, only {available} available")
        self.sku, self.requested, self.available = sku, requested, available
