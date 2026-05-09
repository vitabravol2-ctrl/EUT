from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FsmState(str, Enum):
    IDLE = 'IDLE'
    WAIT_SPREAD = 'WAIT_SPREAD'
    PLACE_BUY = 'PLACE_BUY'
    WAIT_BUY_FILL = 'WAIT_BUY_FILL'
    PLACE_SELL = 'PLACE_SELL'
    WAIT_SELL_FILL = 'WAIT_SELL_FILL'
    LOCK_PROFIT = 'LOCK_PROFIT'
    ERROR = 'ERROR'
    PAUSED = 'PAUSED'


@dataclass
class RuntimeFSM:
    state: FsmState = FsmState.IDLE
    cycle: int = 0
    last_transition: str = 'INIT'
    last_error: str = ''

    def transition(self, new_state: FsmState, reason: str = '') -> None:
        prev = self.state
        self.state = new_state
        self.last_transition = f'{prev.value} -> {new_state.value}' + (f' ({reason})' if reason else '')
        if new_state == FsmState.WAIT_SPREAD and prev == FsmState.LOCK_PROFIT:
            self.cycle += 1

    def set_error(self, message: str) -> None:
        self.last_error = message
        self.transition(FsmState.ERROR, 'error')

    def reset(self) -> None:
        self.last_error = ''
        self.transition(FsmState.IDLE, 'reset')
