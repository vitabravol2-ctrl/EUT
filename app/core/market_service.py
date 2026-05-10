from __future__ import annotations

import time
from decimal import Decimal


class MarketService:
    def __init__(self, client, symbol: str) -> None:
        self.client = client
        self.symbol = symbol

    def set_symbol(self, symbol: str) -> None:
        self.symbol = symbol
        self.last_update = 0.0
        self.tick_size: Decimal | None = None
        self._tick_warned = False

    def set_tick_size(self, tick_size: Decimal | None) -> None:
        self.tick_size = tick_size if tick_size and tick_size > 0 else None

    def snapshot(self) -> dict:
        start = time.perf_counter()
        last = self.client.get_ticker(self.symbol)
        book = self.client.get_book_ticker(self.symbol)
        latency_ms = (time.perf_counter() - start) * 1000
        bid = Decimal(str(book.get('bidPrice', 0) or 0))
        ask = Decimal(str(book.get('askPrice', 0) or 0))
        spread = ask - bid if ask >= bid else Decimal('0')
        self.last_update = time.time()
        spread_ticks = '-'
        if self.tick_size:
            spread_ticks = str((spread / self.tick_size).normalize()) if spread > 0 else '0'
            self._tick_warned = False
        payload = {
            'last': Decimal(str(last.get('price', 0) or 0)),
            'bid': bid,
            'bid_qty': Decimal(str(book.get('bidQty', 0) or 0)),
            'ask': ask,
            'ask_qty': Decimal(str(book.get('askQty', 0) or 0)),
            'spread': spread,
            'spread_ticks': spread_ticks,
            'rest_age': '0ms',
            'latency_ms': latency_ms,
            'spread_source': spread,
            'best_unchanged': getattr(self, '_prev_best', None) == (bid, ask),
            'tick_warning_needed': not self.tick_size and not self._tick_warned,
        }
        self._prev_best = (bid, ask)
        return payload

