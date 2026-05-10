from __future__ import annotations

import time


class OrderService:
    def __init__(self, client, symbol: str) -> None:
        self.client = client
        self.symbol = symbol

    def set_symbol(self, symbol: str) -> None:
        self.symbol = symbol

    def place_limit(self, side: str, qty: str, price: str) -> dict:
        start = time.perf_counter()
        resp = self.client.create_limit_order(self.symbol, side=side, quantity=qty, price=price)
        resp['_reaction_ms'] = (time.perf_counter() - start) * 1000
        return resp

    def open_orders(self) -> list:
        return self.client.get_open_orders(self.symbol)

    def cancel(self, order_id: int) -> dict:
        start = time.perf_counter()
        resp = self.client.cancel_order(self.symbol, order_id)
        resp['_reaction_ms'] = (time.perf_counter() - start) * 1000
        return resp

    def cancel_all(self) -> list:
        return self.client.cancel_all_orders(self.symbol)

    def order_status(self, order_id: int) -> dict:
        return self.client.get_order(self.symbol, order_id)

    def place_limit_maker(self, side: str, qty: str, price: str) -> dict:
        start = time.perf_counter()
        resp = self.client.create_limit_maker_order(self.symbol, side=side, quantity=qty, price=price)
        resp['_reaction_ms'] = (time.perf_counter() - start) * 1000
        return resp
