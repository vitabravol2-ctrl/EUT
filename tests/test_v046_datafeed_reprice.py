from decimal import Decimal
import time

from app.core.data_feed_manager import DataFeedManager, DataFeedPolicy
from app.core.reprice_policy import QuoteRepricePolicy, RepriceGate, min_profitable_exit


def test_ws_fresh_selected_over_rest():
    m = DataFeedManager(Decimal('0.01'), DataFeedPolicy(1500, 3, 3))
    m.update_rest({'bidPrice': '100', 'askPrice': '101'})
    m.update_ws({'bidPrice': '100.02', 'askPrice': '101.02'})
    bid, ask, src = m.top_bid_ask()
    assert src == 'WS'
    assert bid == Decimal('100.02') and ask == Decimal('101.02')


def test_ws_stale_fallback_rest():
    m = DataFeedManager(Decimal('0.01'), DataFeedPolicy(1, 3, 3))
    m.update_rest({'bidPrice': '100', 'askPrice': '101'})
    m.update_ws({'bidPrice': '99', 'askPrice': '100'})
    time.sleep(0.01)
    _, _, src = m.top_bid_ask()
    assert src == 'REST'


def test_ws_rest_drift_forces_fallback():
    m = DataFeedManager(Decimal('0.01'), DataFeedPolicy(1500, 0, 1))
    m.update_rest({'bidPrice': '100', 'askPrice': '101'})
    m.update_ws({'bidPrice': '100.05', 'askPrice': '101.05'})
    _, _, src = m.top_bid_ask()
    assert src == 'REST'


def test_buy_reprice_skipped_too_fresh_and_noise():
    gate = RepriceGate(QuoteRepricePolicy(5, 2000, 2, True))
    assert gate.allow(is_top=False, quote_age_ms=100, tick_move=Decimal('10')).reason == 'too_fresh'
    assert gate.allow(is_top=False, quote_age_ms=3000, tick_move=Decimal('2')).reason == 'noise'


def test_sell_reprice_blocked_below_min_profitable_exit():
    min_exit = min_profitable_exit(Decimal('80870'), 1, Decimal('0.01'), Decimal('0'))
    best_ask = Decimal('80869.99')
    sell_price = max(best_ask, min_exit)
    assert sell_price == min_exit


def test_zero_fee_btcu_min_exit_formula():
    min_exit = min_profitable_exit(Decimal('80870'), 1, Decimal('0.01'), Decimal('0'))
    assert min_exit == Decimal('80870.01')
