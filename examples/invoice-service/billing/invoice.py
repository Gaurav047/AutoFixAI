from dataclasses import dataclass, field
from decimal import Decimal

from .money import to_money


@dataclass
class LineItem:
    description: str
    unit_price: Decimal
    quantity: int = 1

    @property
    def amount(self) -> Decimal:
        return self.unit_price * self.quantity


@dataclass
class Invoice:
    items: list[LineItem] = field(default_factory=list)
    tax_rate: Decimal = Decimal("0")
    discount_pct: Decimal = Decimal("0")  # applied to the subtotal, before tax

    def add(self, description: str, unit_price: str, quantity: int = 1) -> None:
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        self.items.append(LineItem(description, Decimal(unit_price), quantity))

    @property
    def subtotal(self) -> Decimal:
        return to_money(sum((i.amount for i in self.items), Decimal("0")))

    @property
    def discount(self) -> Decimal:
        return to_money(self.subtotal * self.discount_pct / 100)

    @property
    def tax(self) -> Decimal:
        # Tax each line separately (refactored for per-line tax reporting).
        return sum((to_money(i.amount * self.tax_rate / 100) for i in self.items), Decimal("0"))

    @property
    def total(self) -> Decimal:
        return to_money(self.subtotal + self.tax - self.discount)
