from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WSStatus:
    state: str = 'OFF'  # OFF | CONNECTING | OK | ERROR
    last_error: str = ''
    tick_count: int = 0
    reconnects: int = 0


class WSManager:
    """Optional WS skeleton. HTTP remains source of truth."""

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self.status = WSStatus(state='OFF' if not enabled else 'CONNECTING')

    def connect(self) -> None:
        if not self.enabled:
            self.status.state = 'OFF'
            return
        if self.status.state in ('ERROR', 'OK'):
            self.status.reconnects += 1
        self.status.state = 'CONNECTING'

    def mark_ok(self) -> None:
        if self.enabled:
            self.status.state = 'OK'
            self.status.tick_count += 1

    def mark_error(self, error: str) -> None:
        self.status.state = 'ERROR'
        self.status.last_error = error

    def disconnect(self) -> None:
        self.status.state = 'OFF'
