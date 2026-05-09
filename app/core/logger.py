from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, List


@dataclass
class LogRecord:
    level: str
    message: str
    ts: str


class AppLogger:
    def __init__(self) -> None:
        self._subs: List[Callable[[LogRecord], None]] = []

    def subscribe(self, fn: Callable[[LogRecord], None]) -> None:
        self._subs.append(fn)

    def log(self, level: str, message: str) -> None:
        rec = LogRecord(level=level.upper(), message=message, ts=datetime.now(timezone.utc).strftime('%H:%M:%S'))
        for sub in self._subs:
            sub(rec)
