# EUT v0.2.0 — Deterministic Spread Harvester

EUT is **NOT** a predictive trading AI.

EUT is a **deterministic spread execution engine** built around REST-first market polling and maker-order execution quality.

## Core Philosophy
- No AI trader
- No prediction engine
- No theory/ML subsystem
- No analyzer trees
- No overengineering

Profit target comes from deterministic execution mechanics:
- zero fee assumptions
- stable spread capture
- slow market conditions
- maker fill quality

## Runtime Architecture
`app/core/`
- `runtime_fsm.py`
- `polling_manager.py`
- `spread_detector.py`
- `order_manager.py`
- `fill_tracker.py`
- `risk_guard.py`
- `market_service.py`
- `account_service.py`
- `order_service.py`

## Runtime Flow
MARKET POLL -> spread exists -> spread stable -> place BUY maker -> filled -> place SELL maker -> filled -> lock profit -> repeat.

## GUI Focus (Execution Workstation)
Cockpit exposes:
- top runtime status (FSM, REST, polling, spread)
- spread status panel
- runtime FSM panel
- order activity panel

## Logging Markers
- `[FSM]`
- `[SPREAD]`
- `[ORDER]`
- `[FILL]`
- `[RISK]`

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
