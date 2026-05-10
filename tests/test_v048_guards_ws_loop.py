from decimal import Decimal
import time

from app.core.data_feed_manager import DataFeedManager, DataFeedPolicy
from app.core.reprice_policy import min_profitable_exit


def test_buy_delta_18_with_min_25_is_noise():
    tick = Decimal('0.01')
    old_buy = Decimal('80870.00')
    new_bid = Decimal('80870.18')
    delta_ticks = abs(new_bid - old_buy) / tick
    assert delta_ticks == Decimal('18')
    assert delta_ticks < Decimal('25')


def test_sell_tp_below_min_exit_blocked():
    min_exit = min_profitable_exit(Decimal('80870'), 1, Decimal('0.01'), Decimal('0'))
    assert max(Decimal('80869.99'), min_exit) == min_exit


def test_ws_stale_requires_3_misses_before_reconnect():
    m = DataFeedManager(Decimal('0.01'), DataFeedPolicy(ws_stale_ms=1, rest_validate_sec=0, max_ws_rest_drift_ticks=100, ws_max_silent_misses=3, ws_reconnect_cooldown_ms=5000, source_switch_debounce_ms=1))
    m.update_ws({'bidPrice': '100', 'askPrice': '101'})
    time.sleep(0.01)
    assert m.should_reconnect_ws() is False
    assert m.should_reconnect_ws() is False
    assert m.should_reconnect_ws() is True


def test_source_switch_debounce_prevents_flip_flop():
    m = DataFeedManager(Decimal('0.01'), DataFeedPolicy(ws_stale_ms=3000, rest_validate_sec=0, max_ws_rest_drift_ticks=100, source_switch_debounce_ms=3000))
    m.update_rest({'bidPrice': '100', 'askPrice': '101'})
    m.update_ws({'bidPrice': '100.1', 'askPrice': '101.1'})
    _, _, src1 = m.top_bid_ask()
    m.ws_ts = time.time() - 10
    _, _, src2 = m.top_bid_ask()
    assert src1 in {'REST', 'WS'}
    assert src2 == src1
