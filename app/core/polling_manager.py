from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer


class PollingManager(QObject):
    def __init__(
        self,
        market_cb: Callable[[], None],
        orders_cb: Callable[[], None],
        balances_cb: Callable[[], None],
        market_ms: int,
        orders_ms: int,
        balances_ms: int,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._market_cb = market_cb
        self._orders_cb = orders_cb
        self._balances_cb = balances_cb
        self._timers = {
            'market': QTimer(self),
            'orders': QTimer(self),
            'balances': QTimer(self),
        }
        self._intervals = {'market': market_ms, 'orders': orders_ms, 'balances': balances_ms}
        self._running = False
        self._timers['market'].timeout.connect(self._market_cb)
        self._timers['orders'].timeout.connect(self._orders_cb)
        self._timers['balances'].timeout.connect(self._balances_cb)

    def start(self) -> bool:
        if self._running:
            return False
        for key, timer in self._timers.items():
            timer.start(self._intervals[key])
        self._running = True
        return True

    def stop(self) -> None:
        for timer in self._timers.values():
            timer.stop()
        self._running = False

    def set_intervals(self, market_ms: int, orders_ms: int, balances_ms: int) -> None:
        self._intervals = {'market': market_ms, 'orders': orders_ms, 'balances': balances_ms}
        if self._running:
            for key, timer in self._timers.items():
                timer.setInterval(self._intervals[key])

    @property
    def running(self) -> bool:
        return self._running
