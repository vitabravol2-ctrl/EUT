from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from shiboken6 import isValid


class WorkerSignals(QObject):
    success = Signal(str, object)
    error = Signal(str, str)
    finished = Signal(str)


class _Task(QRunnable):
    def __init__(self, name: str, fn: Callable[[], object], signals: WorkerSignals) -> None:
        super().__init__()
        self.name = name
        self.fn = fn
        self.signals = signals

    def _safe_emit(self, signal: Signal, *args: object) -> None:
        if not isValid(self.signals):
            return
        try:
            signal.emit(*args)
        except RuntimeError:
            return

    def run(self) -> None:
        try:
            result = self.fn()
            self._safe_emit(self.signals.success, self.name, result)
        except Exception as exc:
            self._safe_emit(self.signals.error, self.name, str(exc))
        finally:
            self._safe_emit(self.signals.finished, self.name)


class TaskRunner(QObject):
    def __init__(self, max_threads: int = 4, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.signals = WorkerSignals()
        self._pool = QThreadPool.globalInstance()
        self._pool.setMaxThreadCount(max_threads)
        self._in_flight: set[str] = set()
        self._skipped: dict[str, int] = {}

    def run_task(self, name: str, fn: Callable[[], object]) -> bool:
        if name in self._in_flight:
            self._skipped[name] = self._skipped.get(name, 0) + 1
            return False
        self._in_flight.add(name)
        self._pool.start(_Task(name, fn, self.signals))
        return True

    def finish(self, name: str) -> None:
        self._in_flight.discard(name)

    @property
    def in_flight(self) -> set[str]:
        return set(self._in_flight)

    def skipped(self, name: str) -> int:
        return self._skipped.get(name, 0)
