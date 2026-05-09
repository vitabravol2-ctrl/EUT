# EUT v0.1.0 — REST Manual Trading Cockpit

EUT is a REST-first desktop cockpit for **EURIUSDT** on Binance focused on safe manual LIMIT execution.

## Stage scope (v0.1.0)
- Binance connection and config
- REST market polling (bookTicker + ticker)
- Balances view
- Manual LIMIT BUY/SELL only
- Open orders + cancel selected/all
- Log-driven GUI operations

## Philosophy
- REST-first
- WebSocket optional in future stages
- No indicators
- No AI prediction
- Execution quality over prediction

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

## Security notes
- Trading Enabled defaults OFF.
- Read Only mode supported.
- API secrets are never written to logs.
- LIMIT-only workflow with pre-send validation.

## Helper script
```bash
./scripts/update_and_run.sh
```
The script pulls latest changes, runs tests, installs dependencies, and launches the app.
