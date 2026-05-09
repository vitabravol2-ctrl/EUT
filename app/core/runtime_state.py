from __future__ import annotations

from dataclasses import dataclass, field
import time


@dataclass
class RuntimeState:
    public_rest_state: str = 'STALE'
    account_auth_state: str = 'DISCONNECTED'
    polling_state: str = 'STOPPED'
    trading_enabled: bool = False
    last_rest_update_ts: float = 0.0
    last_orders_update_ts: float = 0.0
    last_balances_update_ts: float = 0.0
    last_latency_ms: float = 0.0
    last_error: str = ''
    private_polling_state: str = 'PAUSED'
    future_ws_status: str = 'OFF'
    future_spread_engine_status: str = 'OFF'
    future_risk_guard_status: str = 'OFF'
    _cycle_stamps: list[float] = field(default_factory=list)

    def set_account_auth(self, state: str, latency_ms: float = 0.0) -> None:
        self.account_auth_state = state
        self.last_latency_ms = max(latency_ms, 0.0)

    def set_polling(self, running: bool) -> None:
        self.polling_state = 'RUNNING' if running else 'STOPPED'

    def mark_rest_update(self) -> None:
        now = time.time()
        self.last_rest_update_ts = now
        self.public_rest_state = 'OK'
        self._cycle_stamps.append(now)
        self._cycle_stamps = [ts for ts in self._cycle_stamps if now - ts <= 5.0]

    def mark_orders_update(self) -> None:
        self.last_orders_update_ts = time.time()

    def mark_balances_update(self) -> None:
        self.last_balances_update_ts = time.time()

    def mark_error(self, message: str) -> None:
        self.last_error = message
        self.public_rest_state = 'ERROR'

    def age_ms(self, ts: float) -> int:
        if ts <= 0:
            return -1
        return int((time.time() - ts) * 1000)

    def update_stale(self, stale_ms: int) -> None:
        if self.public_rest_state == 'ERROR':
            return
        age = self.age_ms(self.last_rest_update_ts)
        self.public_rest_state = 'STALE' if age < 0 or age > stale_ms else 'OK'

    def rest_cycles_per_sec(self) -> float:
        if len(self._cycle_stamps) < 2:
            return 0.0
        elapsed = self._cycle_stamps[-1] - self._cycle_stamps[0]
        if elapsed <= 0:
            return 0.0
        return round((len(self._cycle_stamps) - 1) / elapsed, 2)


    @property
    def rest_status(self) -> str:
        return self.public_rest_state

    @rest_status.setter
    def rest_status(self, value: str) -> None:
        self.public_rest_state = value

    @property
    def connection_state(self) -> str:
        return self.account_auth_state

    @connection_state.setter
    def connection_state(self, value: str) -> None:
        self.account_auth_state = value

    @property
    def last_public_latency_ms(self) -> str:
        return f'{int(max(self.last_latency_ms, 0.0))}ms'
