from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
import time


@dataclass
class FillEvent:
    side: str
    qty: Decimal
    price: Decimal
    quote: Decimal
    timestamp: float


class TradeLedger:
    def __init__(self) -> None:
        self.buy_lots: list[dict[str, Any]] = []
        self.total_buy_qty = Decimal('0')
        self.total_buy_quote = Decimal('0')
        self.total_sell_qty = Decimal('0')
        self.total_sell_quote = Decimal('0')
        self.matched_sell_qty = Decimal('0')
        self.inventory_sell_qty = Decimal('0')
        self.inventory_sell_quote = Decimal('0')
        self.realized_pnl = Decimal('0')
        self.fees = Decimal('0')
        self.completed_cycles = 0
        self.closed_lots = 0
        self.winning_cycles = 0
        self.losing_cycles = 0
        self.spread_captured_ticks_total = Decimal('0')
        self.buy_fills = 0
        self.sell_fills = 0
        self.inventory_sell_fills = 0
        self.last_closed_trade_pnl = Decimal('0')
        self.last_closed_trade_ticks = Decimal('0')
        self.last_fill = FillEvent('NONE', Decimal('0'), Decimal('0'), Decimal('0'), 0.0)

    def record_buy(self, qty: Decimal, price: Decimal, fee: Decimal = Decimal('0'), timestamp: float | None = None) -> dict[str, Any]:
        ts = time.time() if timestamp is None else timestamp
        quote = qty * price
        self.buy_lots.append({'qty': qty, 'price': price, 'quote': quote, 'fee_quote': fee, 'timestamp': ts})
        self.total_buy_qty += qty
        self.total_buy_quote += quote
        self.buy_fills += 1
        self.last_fill = FillEvent('BUY', qty, price, quote, ts)
        return {'quote': quote, 'open_lots': len(self.buy_lots)}

    def record_sell(self, qty: Decimal, price: Decimal, fee: Decimal = Decimal('0'), tick_size: Decimal = Decimal('0'), timestamp: float | None = None) -> dict[str, Any]:
        ts = time.time() if timestamp is None else timestamp
        quote = qty * price
        self.total_sell_qty += qty
        self.total_sell_quote += quote
        self.sell_fills += 1
        self.last_fill = FillEvent('SELL', qty, price, quote, ts)
        remaining = qty
        matched_qty = Decimal('0')
        buy_notional = Decimal('0')
        while remaining > 0 and self.buy_lots:
            lot = self.buy_lots[0]
            take = min(remaining, lot['qty'])
            matched_qty += take
            buy_notional += take * lot['price']
            lot['qty'] -= take
            remaining -= take
            if lot['qty'] <= 0:
                self.buy_lots.pop(0)
        out: dict[str, Any] = {'matched_qty': matched_qty, 'inventory_qty': remaining}
        if matched_qty > 0:
            avg_buy = buy_notional / matched_qty
            gross = matched_qty * (price - avg_buy)
            fees = ((matched_qty * avg_buy) + (matched_qty * price)) * fee
            realized = gross - fees
            ticks = ((price - avg_buy) / tick_size) if tick_size > 0 else Decimal('0')
            self.matched_sell_qty += matched_qty
            self.realized_pnl += realized
            self.last_closed_trade_pnl = realized
            self.last_closed_trade_ticks = ticks
            self.fees += fees
            self.spread_captured_ticks_total += ticks
            self.completed_cycles += 1
            self.closed_lots += 1
            if realized > 0:
                self.winning_cycles += 1
            elif realized < 0:
                self.losing_cycles += 1
            out.update({'avg_buy': avg_buy, 'realized': realized, 'fees': fees, 'ticks': ticks})
        if remaining > 0:
            inv_quote = remaining * price
            self.inventory_sell_fills += 1
            self.inventory_sell_qty += remaining
            self.inventory_sell_quote += inv_quote
            out['inventory_quote'] = inv_quote
        return out

    def snapshot(self) -> dict[str, Any]:
        open_qty = sum((lot['qty'] for lot in self.buy_lots), Decimal('0'))
        open_quote_cost = sum((lot['qty'] * lot['price'] for lot in self.buy_lots), Decimal('0'))
        avg_open_buy = (open_quote_cost / open_qty) if open_qty > 0 else Decimal('0')
        avg_buy = (self.total_buy_quote / self.total_buy_qty) if self.total_buy_qty > 0 else Decimal('0')
        avg_sell = (self.total_sell_quote / self.total_sell_qty) if self.total_sell_qty > 0 else Decimal('0')
        winrate = (Decimal(self.winning_cycles) / Decimal(self.completed_cycles) * Decimal('100')) if self.completed_cycles else Decimal('0')
        turnover_quote = self.total_buy_quote + self.total_sell_quote
        matched_volume_quote = self.total_sell_quote - self.inventory_sell_quote
        return {
            'total_buy_qty': self.total_buy_qty,
            'total_buy_quote': self.total_buy_quote,
            'total_sell_qty': self.total_sell_qty,
            'total_sell_quote': self.total_sell_quote,
            'matched_sell_qty': self.matched_sell_qty,
            'inventory_sell_qty': self.inventory_sell_qty,
            'inventory_sell_quote': self.inventory_sell_quote,
            'turnover_quote': turnover_quote,
            'matched_volume_quote': matched_volume_quote,
            'realized_pnl': self.realized_pnl,
            'fees': self.fees,
            'completed_cycles': self.completed_cycles,
            'winning_cycles': self.winning_cycles,
            'losing_cycles': self.losing_cycles,
            'spread_captured_ticks_total': self.spread_captured_ticks_total,
            'open_position_qty': open_qty,
            'open_quote_cost': open_quote_cost,
            'avg_open_buy': avg_open_buy,
            'avg_buy': avg_buy,
            'avg_sell': avg_sell,
            'winrate': winrate,
            'buy_fills': self.buy_fills,
            'sell_fills': self.sell_fills,
            'closed_trades': self.completed_cycles,
            'closed_sell_events': self.completed_cycles,
            'closed_lots': self.closed_lots,
            'wins': self.winning_cycles,
            'losses': self.losing_cycles,
            'inventory_sell_fills': self.inventory_sell_fills,
            'last_closed_trade_pnl': self.last_closed_trade_pnl,
            'last_closed_trade_ticks': self.last_closed_trade_ticks,
            'total_fills': self.buy_fills + self.sell_fills,
            'last_fill': self.last_fill,
        }

    # backward-compatible aliases
    def on_buy(self, qty: Decimal, price: Decimal, timestamp: float | None = None) -> dict[str, Any]:
        return self.record_buy(qty, price, fee=Decimal('0'), timestamp=timestamp)

    def on_sell(self, qty: Decimal, price: Decimal, fee_rate: Decimal, tick_size: Decimal, timestamp: float | None = None) -> dict[str, Any]:
        return self.record_sell(qty, price, fee=fee_rate, tick_size=tick_size, timestamp=timestamp)
