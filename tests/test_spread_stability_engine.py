from decimal import Decimal

from app.core.spread_stability_engine import ReadinessState, SpreadStabilityEngine


def test_collapse_and_readiness_transitions():
    e = SpreadStabilityEngine(Decimal('0.0001'), min_spread_ticks=2, stable_ms=1, history_seconds=120)
    m1 = e.observe(Decimal('1.1000'), Decimal('1.1003'), latency_ms=10)
    m2 = e.observe(Decimal('1.1000'), Decimal('1.1003'), latency_ms=10)
    assert m2.state.readiness in (ReadinessState.WATCH, ReadinessState.READY)

    m3 = e.observe(Decimal('1.1000'), Decimal('1.1001'), latency_ms=10)
    assert m3.state.readiness == ReadinessState.NOT_READY
    assert m3.state.spread_collapse_count == 1


def test_stable_ratio_is_computed():
    e = SpreadStabilityEngine(Decimal('0.0001'), min_spread_ticks=2, stable_ms=1000, history_seconds=120)
    e.observe(Decimal('1.1000'), Decimal('1.1003'), latency_ms=10)
    e.observe(Decimal('1.1000'), Decimal('1.1003'), latency_ms=10)
    ratio = e.observe(Decimal('1.1000'), Decimal('1.1001'), latency_ms=10).state.stable_spread_ratio
    assert 0.0 <= ratio <= 1.0
