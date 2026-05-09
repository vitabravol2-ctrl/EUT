from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional
from uuid import uuid4


class HarvestMode(str, Enum):
    MANUAL = 'MANUAL'
    PAPER = 'PAPER'
    LIVE_LOCKED = 'LIVE_LOCKED'


class CycleState(str, Enum):
    IDLE = 'IDLE'
    WAIT_READY = 'WAIT_READY'
    PLACE_BUY = 'PLACE_BUY'
    BUY_WORKING = 'BUY_WORKING'
    CANCEL_BUY = 'CANCEL_BUY'
    BUY_PARTIAL = 'BUY_PARTIAL'
    BUY_FILLED = 'BUY_FILLED'
    PLACE_SELL = 'PLACE_SELL'
    SELL_WORKING = 'SELL_WORKING'
    CANCEL_SELL = 'CANCEL_SELL'
    SELL_PARTIAL = 'SELL_PARTIAL'
    SELL_FILLED = 'SELL_FILLED'
    PROFIT_LOCKED = 'PROFIT_LOCKED'
    EXIT_PENDING = 'EXIT_PENDING'
    STOPPED = 'STOPPED'
    ERROR = 'ERROR'
    RESET = 'RESET'


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class HarvestCycle:
    cycle_id: str = field(default_factory=lambda: str(uuid4()))
    state: CycleState = CycleState.IDLE
    target_qty: Decimal = Decimal('0')
    buy_order_id: Optional[int] = None
    sell_order_id: Optional[int] = None
    buy_requested_qty: Decimal = Decimal('0')
    buy_filled_qty: Decimal = Decimal('0')
    buy_avg_price: Decimal = Decimal('0')
    sell_requested_qty: Decimal = Decimal('0')
    sell_filled_qty: Decimal = Decimal('0')
    sell_avg_price: Decimal = Decimal('0')
    open_position_qty: Decimal = Decimal('0')
    closed_qty: Decimal = Decimal('0')
    realized_pnl: Decimal = Decimal('0')
    fees: Decimal = Decimal('0')
    started_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    reason: str = ''

    def transition(self, to_state: CycleState, reason: str = '') -> tuple[CycleState, CycleState]:
        old = self.state
        self.state = to_state
        self.reason = reason
        self.updated_at = _now()
        return old, to_state

    def apply_buy_fill(self, fill_qty: Decimal, fill_price: Decimal) -> None:
        if fill_qty <= 0:
            return
        cost_before = self.buy_avg_price * self.buy_filled_qty
        self.buy_filled_qty += fill_qty
        self.open_position_qty += fill_qty
        self.buy_avg_price = (cost_before + (fill_qty * fill_price)) / self.buy_filled_qty
        self.updated_at = _now()

    def apply_sell_fill(self, fill_qty: Decimal, fill_price: Decimal) -> None:
        if fill_qty <= 0:
            return
        qty = min(fill_qty, self.open_position_qty)
        proceeds_before = self.sell_avg_price * self.sell_filled_qty
        self.sell_filled_qty += qty
        self.sell_avg_price = (proceeds_before + (qty * fill_price)) / self.sell_filled_qty
        self.open_position_qty -= qty
        self.closed_qty += qty
        self.realized_pnl += (fill_price - self.buy_avg_price) * qty
        self.updated_at = _now()

    def next_state_after_buy_cancel(self) -> CycleState:
        return CycleState.WAIT_READY if self.buy_filled_qty <= 0 else CycleState.PLACE_SELL

    def can_place_sell(self) -> bool:
        return self.open_position_qty > 0

    def reset_cycle_accounting(self) -> None:
        self.buy_order_id = None
        self.sell_order_id = None
        self.buy_requested_qty = Decimal('0')
        self.target_qty = Decimal('0')
        self.open_position_qty = Decimal('0')
        self.closed_qty = self.buy_filled_qty
        self.sell_filled_qty = self.buy_filled_qty
        self.updated_at = _now()
