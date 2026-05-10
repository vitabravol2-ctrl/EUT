from decimal import Decimal

from app.core.trade_ledger import TradeLedger


def test_cycle_buy_fill_opens_position():
    l = TradeLedger()
    l.record_buy(Decimal('2'), Decimal('1.1'))
    assert l.snapshot()['open_position_qty'] == Decimal('2')


def test_cycle_sell_fill_closes_position():
    l = TradeLedger()
    l.record_buy(Decimal('2'), Decimal('1.1'))
    l.record_sell(Decimal('2'), Decimal('1.2'))
    assert l.snapshot()['open_position_qty'] == Decimal('0')


def test_market_sell_avg_price_not_zero():
    l = TradeLedger()
    l.record_buy(Decimal('1'), Decimal('1.0'))
    out = l.record_sell(Decimal('1'), Decimal('1.1'))
    assert out['realized'] > Decimal('0')
    assert l.snapshot()['avg_sell'] > Decimal('0')


def test_pnl_closed_trade_correct():
    l = TradeLedger()
    l.record_buy(Decimal('1'), Decimal('1.0'))
    out = l.record_sell(Decimal('1'), Decimal('1.2'), fee=Decimal('0'), tick_size=Decimal('0.0001'))
    assert out['realized'] == Decimal('0.2')


def test_winrate_uses_closed_cycles_only():
    l = TradeLedger()
    l.record_buy(Decimal('1'), Decimal('1.0'))
    l.record_sell(Decimal('2'), Decimal('1.2'))
    s = l.snapshot()
    assert s['completed_cycles'] == 1
    assert s['inventory_sell_qty'] == Decimal('1')
    assert s['winrate'] == Decimal('100')
