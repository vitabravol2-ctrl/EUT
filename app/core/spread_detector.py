from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class SpreadStatus:
    spread: float
    spread_ticks: int
    lifetime_ms: int
    is_stable: bool


class SpreadDetector:
    def __init__(self, tick_size: float = 0.0001, min_ticks: int = 1, stable_ms: int = 1200) -> None:
        self.tick_size = tick_size
        self.min_ticks = min_ticks
        self.stable_ms = stable_ms
        self._last_signature: tuple[float, float] | None = None
        self._since_ts: float = 0.0

    def evaluate(self, bid: float, ask: float) -> SpreadStatus:
        now = time.time()
        spread = max(ask - bid, 0.0)
        ticks = int(spread / self.tick_size) if self.tick_size > 0 else 0
        signature = (bid, ask)
        if self._last_signature != signature:
            self._last_signature = signature
            self._since_ts = now
        lifetime_ms = int((now - self._since_ts) * 1000) if self._since_ts else 0
        stable = spread > 0 and ticks >= self.min_ticks and lifetime_ms >= self.stable_ms
        return SpreadStatus(spread=spread, spread_ticks=ticks, lifetime_ms=lifetime_ms, is_stable=stable)
