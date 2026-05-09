from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


def _to_float(value, default=0.0):
    try:
        if isinstance(value, str):
            value = value.strip()
            if value in {'', '-', '—', 'N/A', 'n/a', 'None', 'none', 'null'}:
                return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _to_int(value, default=0):
    try:
        if isinstance(value, str):
            value = value.strip()
            if value in {'', '-', '—', 'N/A', 'n/a', 'None', 'none', 'null'}:
                return int(default)
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


class HarvestReadinessState(str, Enum):
    READY = 'READY'
    WATCH = 'WATCH'
    NOT_READY = 'NOT_READY'
    BLOCKED = 'BLOCKED'


@dataclass
class HarvestReadinessResult:
    state: HarvestReadinessState
    score: int
    reasons: list[str]
    spread_ok: bool
    stability_ok: bool
    latency_ok: bool
    queue_ok: bool
    entry_possible: bool
    exit_possible: bool
    suggested_side: str


class HarvestReadinessEngine:
    def analyze(self, market_snapshot, execution_metrics, filters, balances, open_orders):
        market_snapshot = market_snapshot or {}
        execution_metrics = execution_metrics or {}
        balances = balances or {}
        open_orders = open_orders or []

        spread_ticks = _to_float(market_snapshot.get('spread_ticks', 0.0), 0.0)
        lifetime_ms = _to_int(market_snapshot.get('spread_lifetime_ms', 0), 0)
        latency_ms = _to_float(execution_metrics.get('latency_ms', 0.0), 0.0)
        queue_quality = str(execution_metrics.get('queue_quality', 'MEDIUM') or 'MEDIUM').upper()
        best_unchanged = bool(market_snapshot.get('best_unchanged', False))
        spread_stability = str(execution_metrics.get('spread_stability', 'BAD') or 'BAD').upper()

        filters_loaded = bool(filters) and bool(filters.get('PRICE_FILTER')) and bool(filters.get('LOT_SIZE'))
        account_connected = bool(balances.get('account_connected', False))
        trading_enabled = bool(balances.get('trading_enabled', False))
        read_only = bool(balances.get('read_only', True))
        risk_blocked = bool(balances.get('risk_blocked', False))
        active_orders_limit = max(1, _to_int(balances.get('max_active_orders', 10), 10))

        active_orders = [o for o in open_orders if str(o.get('status', 'NEW')).upper() in {'NEW', 'PARTIALLY_FILLED'}]
        too_many_orders = len(active_orders) > active_orders_limit
        conflicting = any(str(o.get('side', '')).upper() == 'SELL' for o in active_orders)

        spread_ok = spread_ticks >= 1
        stability_ok = lifetime_ms >= 3000 and spread_stability in {'STABLE', 'VERY_STABLE'} and best_unchanged
        latency_ok = latency_ms <= 1500
        queue_ok = queue_quality in {'GOOD', 'MEDIUM'}
        entry_possible = spread_ok and latency_ok and queue_ok and not conflicting
        exit_possible = spread_ok and stability_ok and latency_ok

        score = 0
        score += min(30, int(max(spread_ticks, 0) * 10))
        score += min(25, int(max(lifetime_ms, 0) / 3000 * 25))
        if latency_ms <= 400:
            score += 15
        elif latency_ms <= 900:
            score += 10
        elif latency_ms <= 1500:
            score += 5
        if queue_quality == 'GOOD':
            score += 15
        elif queue_quality == 'MEDIUM':
            score += 8
        if account_connected and filters_loaded and not risk_blocked and trading_enabled and not read_only:
            score += 15
        elif account_connected and filters_loaded and not risk_blocked:
            score += 8
        score = max(0, min(score, 100))

        reasons: list[str] = []
        blocked_reasons: list[str] = []
        if read_only:
            blocked_reasons.append('read_only on')
        if not trading_enabled:
            blocked_reasons.append('trading disabled')
        if risk_blocked:
            blocked_reasons.append('risk block')
        if too_many_orders:
            blocked_reasons.append('too many active orders')
        if filters is not None and not filters_loaded:
            blocked_reasons.append('invalid filters')

        if blocked_reasons:
            return HarvestReadinessResult(HarvestReadinessState.BLOCKED, score, blocked_reasons, spread_ok, stability_ok, latency_ok, queue_ok, False, False, 'NONE')

        if not filters_loaded:
            reasons.append('filters missing')
        if not account_connected:
            reasons.append('account disconnected')
        if not spread_ok:
            reasons.append('spread too small')
        if not latency_ok:
            reasons.append('latency too high')
        if not stability_ok and spread_ok:
            reasons.append('waiting stability')

        if filters_loaded and account_connected and spread_ok and stability_ok and latency_ok and not conflicting:
            return HarvestReadinessResult(HarvestReadinessState.READY, score, ['spread and latency ready'], spread_ok, stability_ok, latency_ok, queue_ok, entry_possible, exit_possible, 'BUY')

        if spread_ok and (lifetime_ms < 3000 or queue_quality == 'MEDIUM' or (1500 >= latency_ms > 900) or not best_unchanged):
            return HarvestReadinessResult(HarvestReadinessState.WATCH, score, reasons or ['watch market'], spread_ok, stability_ok, latency_ok, queue_ok, entry_possible, exit_possible, 'NONE')

        return HarvestReadinessResult(HarvestReadinessState.NOT_READY, score, reasons or ['market not ready'], spread_ok, stability_ok, latency_ok, queue_ok, entry_possible, exit_possible, 'NONE')
