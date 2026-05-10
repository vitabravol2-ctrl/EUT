from decimal import Decimal

from app.core.harvest_cycle import HarvestCycle


def test_sell_fill_excess_does_not_make_net_inventory_negative():
    c = HarvestCycle()
    c.apply_buy_fill(Decimal('0.01'), Decimal('100'))
    c.apply_sell_fill(Decimal('0.03'), Decimal('101'))
    assert c.net_inventory_euri == Decimal('0')
    assert c.open_position_qty == Decimal('0')
