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
    'harvest_mode': 'MANUAL',
    'max_buy_usdt_exposure': 10.0,
    'max_sell_usdt_exposure': 10.0,
    'min_spread_ticks': 2,
    'target_profit_ticks': 1,
    'min_stable_ms': 3000,
    'max_active_cycle': 1,
    'allow_partial_fills': True,
    'min_partial_fill_euri': 0.0,
    'reprice_on_move': True,
    'cancel_on_spread_collapse': True,
    'stop_after_n_failed_cycles': 3,
    'risk_guard_enabled': False,
    'max_long_inventory_euri': 500.0,
    'max_short_inventory_euri': -500.0,
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
