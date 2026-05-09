from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable


@dataclass
class LogRecord:
    level: str
    message: str
    ts: str


class AppLogger:
    def __init__(self, max_records: int = 1000) -> None:
        self._subs: list[Callable[[LogRecord], None]] = []
        self.max_records = max_records
        self._records: list[LogRecord] = []
        self._last_key = ''
        self._last_count = 0

    def subscribe(self, fn: Callable[[LogRecord], None]) -> None:
        self._subs.append(fn)

    def log(self, level: str, message: str) -> None:
        lvl = level.upper()
        key = f'{lvl}:{message}'
        if key == self._last_key:
            self._last_count += 1
            if self._last_count % 10 != 0:
                return
            message = f'{message} (x{self._last_count})'
        else:
            self._last_key = key
            self._last_count = 1

        rec = LogRecord(level=lvl, message=message, ts=datetime.now(timezone.utc).strftime('%H:%M:%S.%f')[:-3])
        self._records.append(rec)
        if len(self._records) > self.max_records:
            self._records = self._records[-self.max_records :]
        for sub in self._subs:
            sub(rec)
