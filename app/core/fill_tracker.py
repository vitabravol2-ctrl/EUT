from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class FillStats:
    total_orders: int = 0
    full_fills: int = 0
    partial_fills: int = 0
    avg_fill_time_ms: float = 0.0
    _fill_times: list[int] = field(default_factory=list)


class FillTracker:
    def __init__(self) -> None:
        self._started: dict[int, float] = {}
        self.stats = FillStats()

    def start(self, order_id: int) -> None:
        self._started[order_id] = time.time()
        self.stats.total_orders += 1

    def update(self, order: dict) -> str:
        order_id = int(order.get('orderId', 0) or 0)
        status = str(order.get('status', ''))
        if status == 'PARTIALLY_FILLED':
            self.stats.partial_fills += 1
            return 'partial'
        if status == 'FILLED':
            self.stats.full_fills += 1
            if order_id in self._started:
                fill_ms = int((time.time() - self._started.pop(order_id)) * 1000)
                self.stats._fill_times.append(fill_ms)
                self.stats.avg_fill_time_ms = round(sum(self.stats._fill_times) / len(self.stats._fill_times), 2)
            return 'full'
        return 'none'
