from decimal import Decimal

import pytest

from billing import Invoice


def make(tax="0", discount="0"):
    return Invoice(tax_rate=Decimal(tax), discount_pct=Decimal(discount))


def test_subtotal():
    inv = make()
    inv.add("Widget", "19.99", 3)
    inv.add("Gadget", "5.00")
    assert inv.subtotal == Decimal("64.97")


def test_tax_without_discount():
    inv = make(tax="8.25")
    inv.add("Widget", "19.99", 3)
    inv.add("Gadget", "5.00")
    assert inv.tax == Decimal("5.36")
    assert inv.total == Decimal("70.33")


def test_discount_is_applied_before_tax():
    inv = make(tax="10", discount="20")
    inv.add("Consulting", "150.00", 2)
    # 300.00 - 20% = 240.00, + 10% tax = 264.00
    assert inv.discount == Decimal("60.00")
    assert inv.tax == Decimal("24.00")
    assert inv.total == Decimal("264.00")


def test_tax_is_rounded_once_on_the_taxable_amount():
    inv = make(tax="7.5")
    for _ in range(3):
        inv.add("Sticker", "0.10")
    # 0.30 * 7.5% = 0.0225 -> 0.02 (per-line rounding would give 0.03)
    assert inv.tax == Decimal("0.02")


def test_rejects_non_positive_quantity():
    with pytest.raises(ValueError):
        make().add("Nothing", "1.00", 0)
