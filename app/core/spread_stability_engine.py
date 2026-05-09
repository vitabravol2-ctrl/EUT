from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from time import time


class ReadinessState(str, Enum):
    NOT_READY = 'NOT_READY'
    WATCH = 'WATCH'
    READY = 'READY'


@dataclass
class SpreadSnapshot:
    timestamp: float
    bid: Decimal
    ask: Decimal
    spread: Decimal
    spread_ticks: Decimal


@dataclass
class SpreadState:
    spread_lifetime_ms: int
    best_bid_unchanged_ms: int
    best_ask_unchanged_ms: int
    spread_collapse_count: int
    stable_spread_ratio: float
    readiness: ReadinessState


@dataclass
class SpreadMetrics:
    snapshot: SpreadSnapshot
    state: SpreadState


class SpreadStabilityEngine:
    def __init__(self, tick_size: Decimal, min_spread_ticks: int, stable_ms: int, history_seconds: int = 300, stay_ready_ticks: int = 1, ready_hysteresis_ms: int = 12000) -> None:
        self.tick_size = tick_size if tick_size > 0 else Decimal('0.0001')
        self.min_spread_ticks = max(min_spread_ticks, 1)
        self.stable_ms = max(stable_ms, 1)
        self.history_seconds = max(history_seconds, 120)
        self._history: deque[SpreadSnapshot] = deque()
        self._pair_since: float | None = None
        self._bid_since: float | None = None
        self._ask_since: float | None = None
        self._last_pair: tuple[Decimal, Decimal] | None = None
        self._last_bid: Decimal | None = None
        self._last_ask: Decimal | None = None
        self._collapse_count = 0
        self._last_above_target = False
        self._last_ready_ts: float | None = None
        self.stay_ready_ticks = max(stay_ready_ticks, 1)
        self.ready_hysteresis_ms = max(ready_hysteresis_ms, 0)

    def observe(self, bid: Decimal, ask: Decimal, latency_ms: float) -> SpreadMetrics:
        ts = time()
        spread = ask - bid if ask >= bid else Decimal('0')
        spread_ticks = (spread / self.tick_size) if self.tick_size > 0 else Decimal('0')
        snapshot = SpreadSnapshot(ts, bid, ask, spread, spread_ticks)
        self._history.append(snapshot)
        self._trim_history(ts)

        pair = (bid, ask)
        if pair != self._last_pair:
            self._last_pair = pair
            self._pair_since = ts
        if bid != self._last_bid:
            self._last_bid = bid
            self._bid_since = ts
        if ask != self._last_ask:
            self._last_ask = ask
            self._ask_since = ts

        above_target = spread_ticks >= Decimal(self.min_spread_ticks)
        if self._last_above_target and not above_target:
            self._collapse_count += 1
        self._last_above_target = above_target

        pair_ms = int((ts - (self._pair_since or ts)) * 1000)
        bid_ms = int((ts - (self._bid_since or ts)) * 1000)
        ask_ms = int((ts - (self._ask_since or ts)) * 1000)
        ratio = self._stable_ratio()
        readiness = self._resolve_readiness(above_target, pair_ms, bid_ms, ask_ms, latency_ms, spread_ticks, ts)

        return SpreadMetrics(
            snapshot=snapshot,
            state=SpreadState(
                spread_lifetime_ms=pair_ms,
                best_bid_unchanged_ms=bid_ms,
                best_ask_unchanged_ms=ask_ms,
                spread_collapse_count=self._collapse_count,
                stable_spread_ratio=ratio,
                readiness=readiness,
            ),
        )

    def _trim_history(self, now_ts: float) -> None:
        border = now_ts - self.history_seconds
        while self._history and self._history[0].timestamp < border:
            self._history.popleft()

    def _stable_ratio(self) -> float:
        if len(self._history) < 2:
            return 0.0
        stable_secs = 0.0
        total_secs = 0.0
        items = list(self._history)
        for i in range(1, len(items)):
            dt = max(items[i].timestamp - items[i - 1].timestamp, 0.0)
            total_secs += dt
            if items[i].spread_ticks >= Decimal(self.min_spread_ticks):
                stable_secs += dt
        if total_secs <= 0:
            return 0.0
        return stable_secs / total_secs

    def _resolve_readiness(self, above_target: bool, pair_ms: int, bid_ms: int, ask_ms: int, latency_ms: float, spread_ticks: Decimal, ts: float) -> ReadinessState:
        latency_ok = latency_ms <= 1000
        stable_now = pair_ms >= self.stable_ms and bid_ms >= self.stable_ms and ask_ms >= self.stable_ms
        if above_target and stable_now and latency_ok:
            self._last_ready_ts = ts
            return ReadinessState.READY
        if self._last_ready_ts is not None and spread_ticks >= Decimal(self.stay_ready_ticks):
            if (ts - self._last_ready_ts) * 1000 <= self.ready_hysteresis_ms:
                return ReadinessState.READY
        if above_target:
            return ReadinessState.WATCH
        return ReadinessState.NOT_READY
