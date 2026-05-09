from __future__ import annotations

import time


class MarketService:
    def __init__(self, client, symbol: str) -> None:
        self.client = client
        self.symbol = symbol
        self.last_update = 0.0

    def snapshot(self) -> dict:
        last = self.client.get_ticker(self.symbol)
        book = self.client.get_book_ticker(self.symbol)
        bid = float(book.get('bidPrice', 0) or 0)
        ask = float(book.get('askPrice', 0) or 0)
        spread = max(ask - bid, 0.0)
        self.last_update = time.time()
        return {
            'last': float(last.get('price', 0) or 0),
            'bid': bid,
            'bid_qty': float(book.get('bidQty', 0) or 0),
            'ask': ask,
            'ask_qty': float(book.get('askQty', 0) or 0),
            'spread': spread,
            'spread_ticks': int(spread / 0.0001) if spread else 0,
            'age_ms': 0,
        }
