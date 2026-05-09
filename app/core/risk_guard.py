from __future__ import annotations

import time


class RiskGuard:
    def __init__(self, max_position_size: float = 5000.0, max_active_orders: int = 1, market_stale_ms: int = 3000) -> None:
        self.max_position_size = max_position_size
        self.max_active_orders = max_active_orders
        self.market_stale_ms = market_stale_ms
        self.emergency_stop = False

    def check(self, *, position_size: float, active_orders: int, spread_ticks: int, last_market_update_ts: float) -> tuple[bool, str]:
        if self.emergency_stop:
            return False, 'emergency stop'
        if position_size > self.max_position_size:
            return False, 'max position exceeded'
        if active_orders > self.max_active_orders:
            return False, 'too many active orders'
        if spread_ticks <= 0:
            return False, 'invalid spread'
        if last_market_update_ts <= 0 or int((time.time() - last_market_update_ts) * 1000) > self.market_stale_ms:
            return False, 'market stale'
        return True, 'ok'

    def stop(self) -> None:
        self.emergency_stop = True

    def resume(self) -> None:
        self.emergency_stop = False
