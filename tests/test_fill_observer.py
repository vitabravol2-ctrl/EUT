from decimal import Decimal

from app.core.fill_observer import FillObserver, MarketActivity


def test_spread_ticks_math_btcu_reference_case():
    bid = Decimal('80760.01')
    ask = Decimal('80764.81')
    tick_size = Decimal('0.01')
    assert (ask - bid) / tick_size == Decimal('480')


def test_spread_ticks_math_euri_reference_case():
    spread = Decimal('0.0002')
    tick_size = Decimal('0.0001')
    assert spread / tick_size == Decimal('2')


def test_fill_window_and_possible_transition():
    t = [100.0]
    observer = FillObserver(min_spread_ticks=2, stable_ms=1000, now_fn=lambda: t[0])

    first = observer.observe(Decimal('1.1000'), Decimal('1.1003'), Decimal('3'), 0)
    assert first.fill_window_estimate_ms == 0
    assert first.fill_possible is False

    t[0] = 101.2
    second = observer.observe(Decimal('1.1000'), Decimal('1.1003'), Decimal('3'), 1200)
    assert second.bid_lifetime_ms >= 1200
    assert second.ask_lifetime_ms >= 1200
    assert second.fill_window_estimate_ms >= 1200
    assert second.fill_possible is True


def test_market_activity_levels():
    t = [1.0]
    observer = FillObserver(min_spread_ticks=2, stable_ms=1000, now_fn=lambda: t[0])

    observer.observe(Decimal('1.1000'), Decimal('1.1003'), Decimal('3'), 0)
    t[0] = 1.2
    high = observer.observe(Decimal('1.1001'), Decimal('1.1004'), Decimal('3'), 200)
    assert high.market_activity == MarketActivity.HIGH

    t[0] = 1.7
    medium = observer.observe(Decimal('1.1001'), Decimal('1.1004'), Decimal('3'), 700)
    assert medium.market_activity == MarketActivity.MEDIUM

    t[0] = 2.8
    low = observer.observe(Decimal('1.1001'), Decimal('1.1004'), Decimal('3'), 1800)
    assert low.market_activity == MarketActivity.LOW


def test_fill_window_threshold_can_be_shorter_than_stable_ms():
    t = [10.0]
    observer = FillObserver(min_spread_ticks=1, stable_ms=500, fill_window_ms=300, now_fn=lambda: t[0])
    observer.observe(Decimal('1.1000'), Decimal('1.1003'), Decimal('3'), 0)
    t[0] = 10.55
    obs = observer.observe(Decimal('1.1000'), Decimal('1.1003'), Decimal('3'), 550)
    assert obs.fill_window_estimate_ms >= 550
    assert obs.fill_possible is True


def test_high_activity_not_blocking_by_default():
    t = [1.0]
    observer = FillObserver(min_spread_ticks=1, stable_ms=500, fill_window_ms=100, block_high_activity=False, now_fn=lambda: t[0])
    observer.observe(Decimal('1.1000'), Decimal('1.1003'), Decimal('3'), 0)
    t[0] = 1.2
    obs = observer.observe(Decimal('1.1000'), Decimal('1.1003'), Decimal('3'), 600)
    assert obs.market_activity == MarketActivity.HIGH
    assert obs.fill_possible is True


def test_btcu_fast_mode_does_not_require_long_window_or_stability():
    t = [1.0]
    observer = FillObserver(min_spread_ticks=2, stable_ms=3000, symbol='BTCU', fill_window_ms=3000, block_high_activity=True, now_fn=lambda: t[0])
    obs = observer.observe(Decimal('80760.01'), Decimal('80764.81'), Decimal('480'), 10)
    assert obs.market_activity == MarketActivity.HIGH
    assert obs.fill_possible is True


def test_euri_keeps_stability_gate():
    t = [1.0]
    observer = FillObserver(min_spread_ticks=2, stable_ms=1000, symbol='EURIUSDT', fill_window_ms=1000, now_fn=lambda: t[0])
    obs = observer.observe(Decimal('1.1000'), Decimal('1.1002'), Decimal('2'), 10)
    assert obs.fill_possible is False
