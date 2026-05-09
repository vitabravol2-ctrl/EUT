from __future__ import annotations

import time


class OrderManager:
    def __init__(self, order_service) -> None:
        self.order_service = order_service
        self.active_order: dict | None = None
        self.reprices_count = 0
        self.submitted_ts = 0.0

    def place_maker(self, side: str, qty: str, price: str) -> dict:
        if self.active_order and self.active_order.get('status') in {'NEW', 'PARTIALLY_FILLED'}:
            raise RuntimeError('active order already exists')
        order = self.order_service.place_limit(side=side, qty=qty, price=price)
        order.setdefault('status', 'NEW')
        self.active_order = order
        self.submitted_ts = time.time()
        return order

    def cancel_active(self) -> dict | None:
        if not self.active_order:
            return None
        result = self.order_service.cancel(self.active_order['orderId'])
        self.active_order = None
        self.submitted_ts = 0.0
        return result

    def replace(self, side: str, qty: str, price: str) -> dict:
        self.cancel_active()
        self.reprices_count += 1
        return self.place_maker(side=side, qty=qty, price=price)

    def alive_time_ms(self) -> int:
        if not self.active_order or self.submitted_ts <= 0:
            return 0
        return int((time.time() - self.submitted_ts) * 1000)
