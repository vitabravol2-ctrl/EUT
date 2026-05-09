from __future__ import annotations


class OrderService:
    def __init__(self, client, symbol: str) -> None:
        self.client = client
        self.symbol = symbol

    def place_limit(self, side: str, qty: str, price: str) -> dict:
        return self.client.create_limit_order(self.symbol, side=side, quantity=qty, price=price)

    def open_orders(self) -> list:
        return self.client.get_open_orders(self.symbol)

    def cancel(self, order_id: int) -> dict:
        return self.client.cancel_order(self.symbol, order_id)

    def cancel_all(self) -> list:
        return self.client.cancel_all_orders(self.symbol)
