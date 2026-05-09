from decimal import Decimal
import time

from app.core.spread_stability_engine import ReadinessState, SpreadStabilityEngine


def test_ready_hysteresis_stays_ready_on_one_tick():
    e = SpreadStabilityEngine(Decimal('0.0001'), min_spread_ticks=2, stable_ms=1, stay_ready_ticks=1, ready_hysteresis_ms=15000)
    m_ready = None
    for _ in range(5):
        m_ready = e.observe(Decimal('1.1000'), Decimal('1.1003'), latency_ms=10)
        time.sleep(0.002)
    assert m_ready is not None and m_ready.state.readiness == ReadinessState.READY

    m_hold = e.observe(Decimal('1.1000'), Decimal('1.1001'), latency_ms=10)
    assert m_hold.state.readiness == ReadinessState.READY


def test_not_ready_when_spread_collapses_to_zero():
    e = SpreadStabilityEngine(Decimal('0.0001'), min_spread_ticks=2, stable_ms=1, stay_ready_ticks=1, ready_hysteresis_ms=15000)
    e.observe(Decimal('1.1000'), Decimal('1.1003'), latency_ms=10)
    e.observe(Decimal('1.1000'), Decimal('1.1003'), latency_ms=10)
    m = e.observe(Decimal('1.1000'), Decimal('1.1000'), latency_ms=10)
    assert m.state.readiness == ReadinessState.NOT_READY
