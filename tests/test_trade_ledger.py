from decimal import Decimal

from app.core.trade_ledger import TradeLedger


def test_buy_sell_full_match_realized_and_winrate():
    l = TradeLedger()
    l.on_buy(Decimal('1'), Decimal('100'))
    l.on_sell(Decimal('1'), Decimal('101'), Decimal('0'), Decimal('0.01'))
    s = l.snapshot()
    assert s['realized_pnl'] == Decimal('1')
    assert s['completed_cycles'] == 1
    assert s['winrate'] == Decimal('100')


def test_partial_sell_keeps_open_position():
    l = TradeLedger()
    l.on_buy(Decimal('1'), Decimal('100'))
    l.on_sell(Decimal('0.4'), Decimal('101'), Decimal('0'), Decimal('0.01'))
    s = l.snapshot()
    assert s['open_position_qty'] == Decimal('0.6')
    assert s['realized_pnl'] == Decimal('0.4')


def test_sell_without_buys_goes_to_inventory_only():
    l = TradeLedger()
    l.on_sell(Decimal('1'), Decimal('101'), Decimal('0'), Decimal('0.01'))
    s = l.snapshot()
    assert s['inventory_sell_qty'] == Decimal('1')
    assert s['realized_pnl'] == Decimal('0')


def test_sell_excess_splits_matched_and_inventory():
    l = TradeLedger()
    l.on_buy(Decimal('1'), Decimal('100'))
    l.on_sell(Decimal('1.5'), Decimal('101'), Decimal('0'), Decimal('0.01'))
    s = l.snapshot()
    assert s['matched_sell_qty'] == Decimal('1')
    assert s['inventory_sell_qty'] == Decimal('0.5')


def test_zero_fee_profile_keeps_fees_zero():
    l = TradeLedger()
    l.on_buy(Decimal('1'), Decimal('100'))
    l.on_sell(Decimal('1'), Decimal('101'), Decimal('0'), Decimal('0.01'))
    assert l.snapshot()['fees'] == Decimal('0')
