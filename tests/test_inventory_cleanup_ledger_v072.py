from decimal import Decimal

from app.core.trade_ledger import TradeLedger


def test_inventory_sell_not_counted_as_closed_trade():
    l = TradeLedger()
    l.record_sell(Decimal('2'), Decimal('1.2'), tick_size=Decimal('0.0001'))
    s = l.snapshot()
    assert s['completed_cycles'] == 0
    assert s['inventory_sell_qty'] == Decimal('2')
