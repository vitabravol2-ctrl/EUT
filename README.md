# EUT v0.1.1 — Cockpit Stability + Runtime Foundation

## Architecture
- `app/core/runtime_state.py`: centralized runtime status model.
- `app/core/polling_manager.py`: independent market/orders/balances timers with duplicate-start protection.
- GUI (`app/gui/main_window.py`) consumes runtime state and polling manager, avoiding direct ad-hoc runtime storage.

## Runtime Foundation
- Runtime status bar: connection, runtime, polling, latency, REST age, orders age, trading state.
- REST status states: `OK / STALE / ERROR`.
- Future placeholders already visible: `WS`, `Spread Engine`, `Risk Guard`.

## Polling
- Independent intervals for market, orders, balances.
- Safe `start/stop` lifecycle.
- Duplicate timer protection prevents runaway timers.
- Stale detection based on last REST timestamp age.

## GUI Philosophy
- Terminal-style dark cockpit.
- Stable split layout: top status bar, left market/balances/quick stats, center manual trading, right open orders, bottom logs.
- Compact widgets, fixed visual rhythm, sortable orders table, categorized logs with millisecond timestamps.

## Future Roadmap (placeholders prepared)
- Spread analyzer
- Queue quality
- Refill detection
- Cycle statistics
- Paper trading
- Execution engine
- Risk guard

## Setup
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run
```bash
python main.py
```
