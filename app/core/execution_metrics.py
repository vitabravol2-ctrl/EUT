from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class OrderTransition:
    order_id: int
    transition: str


class SpreadStabilityAnalyzer:
    def classify(self, spread_ticks: float, lifetime_ms: int) -> str:
        if spread_ticks <= 0:
            return 'BAD'
        if spread_ticks <= 3 and lifetime_ms >= 5000:
            return 'VERY_STABLE'
        if spread_ticks <= 4 and lifetime_ms >= 3000:
            return 'STABLE'
        if lifetime_ms < 1000:
            return 'UNSTABLE'
        return 'BAD'


class QueueQualityEstimator:
    def classify(self, spread_stability: str, best_unchanged: bool, latency_ms: float, latency_threshold_ms: int = 400) -> str:
        if spread_stability in ('VERY_STABLE', 'STABLE') and best_unchanged and latency_ms <= latency_threshold_ms:
            return 'GOOD'
        if spread_stability == 'BAD' or latency_ms > latency_threshold_ms * 1.75:
            return 'POOR'
        return 'MEDIUM'


def format_latency_ms(value: float | int | None) -> str:
    if value is None:
        return '-'
    return f'{int(max(float(value), 0.0))} ms'


def fill_probability_label(full_fills: int, total_orders: int) -> str:
    if total_orders <= 0:
        return '-'
    return f'{int((full_fills / total_orders) * 100)}%'


def last_fill_time_label(ts: float | None) -> str:
    if not ts:
        return '-'
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')


def diff_order_transitions(previous: set[int], current: set[int]) -> list[OrderTransition]:
    events: list[OrderTransition] = []
    for oid in sorted(current - previous):
        events.append(OrderTransition(order_id=oid, transition='NEW'))
    for oid in sorted(previous - current):
        events.append(OrderTransition(order_id=oid, transition='DISAPPEARED'))
    return events
