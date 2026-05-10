from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class DataFeedPolicy:
    ws_stale_ms: int
    rest_validate_sec: int
    max_ws_rest_drift_ticks: int


@dataclass
class DataFeedSnapshot:
    source: str
    ws_age_ms: int
    rest_age_ms: int
    ws_bid: Decimal
    ws_ask: Decimal
    rest_bid: Decimal
    rest_ask: Decimal
    drift_ticks: Decimal
    fallback_reason: str
    status: str


class DataFeedManager:
    def __init__(self, tick_size: Decimal, policy: DataFeedPolicy) -> None:
        self.tick_size = tick_size if tick_size > 0 else Decimal('0.0001')
        self.policy = policy
        self.ws_book: dict[str, Any] | None = None
        self.ws_ts = 0.0
        self.rest_book: dict[str, Any] | None = None
        self.rest_ts = 0.0
        self._last_validate_ts = 0.0
        self._ws_stale_forced = False
        self._fallback_reason = ''

    def update_ws(self, book: dict[str, Any], receive_time: float | None = None) -> None:
        self.ws_book = book
        self.ws_ts = receive_time or time.time()
        self._ws_stale_forced = False

    def update_rest(self, book: dict[str, Any], receive_time: float | None = None) -> None:
        self.rest_book = book
        self.rest_ts = receive_time or time.time()

    def _age_ms(self, ts: float) -> int:
        return int((time.time() - ts) * 1000) if ts > 0 else -1

    def ws_fresh(self) -> bool:
        if self._ws_stale_forced or not self.ws_book:
            return False
        age = self._age_ms(self.ws_ts)
        return age >= 0 and age <= self.policy.ws_stale_ms

    def maybe_validate(self) -> None:
        if not self.ws_book or not self.rest_book:
            return
        now = time.time()
        if (now - self._last_validate_ts) < self.policy.rest_validate_sec:
            return
        self._last_validate_ts = now
        ws_bid = Decimal(str(self.ws_book.get('bidPrice', 0) or 0))
        rest_bid = Decimal(str(self.rest_book.get('bidPrice', 0) or 0))
        drift = abs(ws_bid - rest_bid) / self.tick_size if self.tick_size > 0 else Decimal('0')
        if drift > Decimal(self.policy.max_ws_rest_drift_ticks):
            self._ws_stale_forced = True
            self._fallback_reason = 'drift'

    def top_bid_ask(self) -> tuple[Decimal, Decimal, str]:
        self.maybe_validate()
        if self.ws_fresh() and self.ws_book:
            return (
                Decimal(str(self.ws_book.get('bidPrice', 0) or 0)),
                Decimal(str(self.ws_book.get('askPrice', 0) or 0)),
                'WS',
            )
        if self.rest_book:
            reason = self._fallback_reason or 'ws_stale'
            self._fallback_reason = reason
            return (
                Decimal(str(self.rest_book.get('bidPrice', 0) or 0)),
                Decimal(str(self.rest_book.get('askPrice', 0) or 0)),
                'REST',
            )
        return Decimal('0'), Decimal('0'), 'NONE'

    def diagnostics(self) -> DataFeedSnapshot:
        ws_bid = Decimal(str((self.ws_book or {}).get('bidPrice', 0) or 0))
        ws_ask = Decimal(str((self.ws_book or {}).get('askPrice', 0) or 0))
        rest_bid = Decimal(str((self.rest_book or {}).get('bidPrice', 0) or 0))
        rest_ask = Decimal(str((self.rest_book or {}).get('askPrice', 0) or 0))
        drift = (abs(ws_bid - rest_bid) / self.tick_size) if self.tick_size > 0 else Decimal('0')
        source = 'WS' if self.ws_fresh() else ('REST' if self.rest_book else 'STALE')
        status = 'DATA WS OK' if source == 'WS' else ('DATA REST OK' if source == 'REST' else 'DATA STALE')
        return DataFeedSnapshot(source, self._age_ms(self.ws_ts), self._age_ms(self.rest_ts), ws_bid, ws_ask, rest_bid, rest_ask, drift, self._fallback_reason, status)
