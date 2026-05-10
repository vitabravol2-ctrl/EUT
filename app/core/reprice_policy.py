from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class QuoteRepricePolicy:
    minimum_reprice_ticks: int
    minimum_quote_lifetime_ms: int
    max_reprice_per_sec: int
    do_not_reprice_if_top: bool = True


@dataclass
class RepriceDecision:
    allowed: bool
    reason: str


@dataclass
class RepriceGate:
    policy: QuoteRepricePolicy
    _events: list[float] = field(default_factory=list)

    def allow(self, *, is_top: bool, quote_age_ms: int, tick_move: Decimal) -> RepriceDecision:
        if self.policy.do_not_reprice_if_top and is_top:
            return RepriceDecision(False, 'top')
        if quote_age_ms < self.policy.minimum_quote_lifetime_ms:
            return RepriceDecision(False, 'too_fresh')
        if tick_move < Decimal(self.policy.minimum_reprice_ticks):
            return RepriceDecision(False, 'noise')
        now = time.time()
        self._events = [ts for ts in self._events if now - ts <= 1.0]
        if len(self._events) >= self.policy.max_reprice_per_sec:
            return RepriceDecision(False, 'rate_limit')
        self._events.append(now)
        return RepriceDecision(True, 'ok')


def min_profitable_exit(avg_buy_price: Decimal, target_profit_ticks: int, tick_size: Decimal, fees_buffer: Decimal) -> Decimal:
    return avg_buy_price + (Decimal(target_profit_ticks) * tick_size) + fees_buffer
