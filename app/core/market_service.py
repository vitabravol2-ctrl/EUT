from __future__ import annotations

import time
from decimal import Decimal


class MarketService:
    def __init__(self, client, symbol: str) -> None:
        self.client = client
        self.symbol = symbol
        self.last_update = 0.0

    def snapshot(self) -> dict:
        last = self.client.get_ticker(self.symbol)
        book = self.client.get_book_ticker(self.symbol)
        bid = Decimal(str(book.get('bidPrice', 0) or 0))
        ask = Decimal(str(book.get('askPrice', 0) or 0))
        spread = ask - bid if ask >= bid else Decimal('0')
        tick_size = Decimal('0.0001')
        self.last_update = time.time()
        return {
            'last': Decimal(str(last.get('price', 0) or 0)),
            'bid': bid,
            'bid_qty': Decimal(str(book.get('bidQty', 0) or 0)),
            'ask': ask,
            'ask_qty': Decimal(str(book.get('askQty', 0) or 0)),
            'spread': spread,
            'spread_ticks': int(spread / tick_size) if spread else 0,
            'rest_age': '0ms',
        }
