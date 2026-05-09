from __future__ import annotations

import json
from pathlib import Path

CONFIG_PATH = Path('.env.local.json')

DEFAULT_CONFIG = {
    'api_key': '',
    'api_secret': '',
    'testnet': False,
    'read_only': True,
    'trading_enabled': False,
    'symbol': 'EURIUSDT',
    'poll_interval_ms': 1000,
    'request_timeout_sec': 3,
    'trade_mode': 'MANUAL',
    'future_mode': 'PAPER',
    'min_spread_ticks': 2,
    'stable_ms': 3000,
    'max_order_usdt': 10.0,
    'max_active_orders': 1,
    'risk_guard_enabled': False,
}



def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return DEFAULT_CONFIG.copy()
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
    except Exception:
        return DEFAULT_CONFIG.copy()
    cfg = DEFAULT_CONFIG.copy()
    cfg.update(data)
    return cfg


def save_config(config: dict) -> None:
    cfg = DEFAULT_CONFIG.copy()
    cfg.update(config)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding='utf-8')
