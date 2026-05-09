from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Callable
from time import time


class MarketActivity(str, Enum):
    LOW = 'LOW'
    MEDIUM = 'MEDIUM'
    HIGH = 'HIGH'


@dataclass
class FillObservation:
    bid_lifetime_ms: int
    ask_lifetime_ms: int
    spread_lifetime_ms: int
    fill_window_estimate_ms: int
    market_activity: MarketActivity
    fill_possible: bool


class FillObserver:
    def __init__(self, min_spread_ticks: int, stable_ms: int, now_fn: Callable[[], float] | None = None) -> None:
        self.min_spread_ticks = max(min_spread_ticks, 1)
        self.stable_ms = max(stable_ms, 1)
        self._now_fn = now_fn or time
        self._last_bid: Decimal | None = None
        self._last_ask: Decimal | None = None
        self._bid_since: float | None = None
        self._ask_since: float | None = None

    def observe(self, bid: Decimal, ask: Decimal, spread_ticks: Decimal, spread_lifetime_ms: int) -> FillObservation:
        now = self._now_fn()
        if bid != self._last_bid:
            self._last_bid = bid
            self._bid_since = now
        if ask != self._last_ask:
            self._last_ask = ask
            self._ask_since = now

        bid_ms = int((now - (self._bid_since or now)) * 1000)
        ask_ms = int((now - (self._ask_since or now)) * 1000)
        fill_window_ms = min(bid_ms, ask_ms, max(spread_lifetime_ms, 0))

        activity = self._activity_from_lifetimes(bid_ms, ask_ms)
        fill_possible = (
            spread_ticks >= Decimal(self.min_spread_ticks)
            and spread_lifetime_ms >= self.stable_ms
            and fill_window_ms >= self.stable_ms
        )

        return FillObservation(
            bid_lifetime_ms=bid_ms,
            ask_lifetime_ms=ask_ms,
            spread_lifetime_ms=spread_lifetime_ms,
            fill_window_estimate_ms=fill_window_ms,
            market_activity=activity,
            fill_possible=fill_possible,
        )

    def _activity_from_lifetimes(self, bid_ms: int, ask_ms: int) -> MarketActivity:
        slow_score = min(bid_ms, ask_ms)
        if slow_score >= self.stable_ms:
            return MarketActivity.LOW
        if slow_score >= self.stable_ms // 2:
            return MarketActivity.MEDIUM
        return MarketActivity.HIGH
