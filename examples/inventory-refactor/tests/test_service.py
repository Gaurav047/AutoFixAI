import pytest

from inventory.models import OutOfStock, Product
from inventory.service import InventoryService


@pytest.fixture
def svc():
    s = InventoryService()
    s.add_product(Product("BOLT-M6", "M6 bolt", unit_price=0.40, stock=500))
    s.add_product(Product("NUT-M6", "M6 nut", unit_price=0.12, stock=20))
    return s


def test_restock_adds_stock(svc):
    assert svc.restock("NUT-M6", 30) == 50
    assert svc.get("NUT-M6").stock == 50


def test_quote_small_order_has_no_discount(svc):
    assert svc.quote("BOLT-M6", 5) == 2.00


def test_quote_applies_bulk_tier(svc):
    # 120 x 0.40 = 48.00, 15% off = 40.80
    assert svc.quote("BOLT-M6", 120) == 40.80


def test_place_order_decrements_stock(svc):
    assert svc.place_order("BOLT-M6", 10) == 3.80
    assert svc.get("BOLT-M6").stock == 490


def test_out_of_stock(svc):
    with pytest.raises(OutOfStock):
        svc.place_order("NUT-M6", 21)
