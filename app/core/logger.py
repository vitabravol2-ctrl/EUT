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
    def __init__(self, max_records: int = 1000, dedupe_seconds: float = 10.0) -> None:
        self._subs: list[Callable[[LogRecord], None]] = []
        self.max_records = max_records
        self._records: list[LogRecord] = []
        self.dedupe_seconds = dedupe_seconds
        self._seen: dict[str, float] = {}

    def subscribe(self, fn: Callable[[LogRecord], None]) -> None:
        self._subs.append(fn)

    def log(self, level: str, message: str) -> None:
        lvl = level.upper()
        now = datetime.now(timezone.utc).timestamp()
        key = f'{lvl}:{message}'
        last = self._seen.get(key)
        if last is not None and now - last < self.dedupe_seconds:
            return
        self._seen[key] = now
        rec = LogRecord(level=lvl, message=message, ts=datetime.now(timezone.utc).strftime('%H:%M:%S.%f')[:-3])
        self._records.append(rec)
        if len(self._records) > self.max_records:
            self._records = self._records[-self.max_records :]
        for sub in self._subs:
            sub(rec)
