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
    'enable_inventory_cleanup': False,
    'min_spread_ticks': 2,
    'target_profit_ticks': 1,
    'min_stable_ms': 3000,
    'max_active_cycle': 1,
    'allow_partial_fills': True,
    'min_partial_fill_euri': 0.0,
    'min_resize_delta_euri': 1.0,
    'reprice_on_move': True,
    'cancel_on_spread_collapse': True,
    'stop_after_n_failed_cycles': 3,
    'risk_guard_enabled': False,
    'max_long_inventory_euri': 500.0,
    'max_short_inventory_euri': -500.0,
    'target_inventory_ratio': 0.50,
    'inventory_soft_limit': 0.65,
    'inventory_hard_limit': 0.80,
    'min_buy_free_usdt': 5.0,
    'min_sell_free_euri': 1.0,
    'minimum_reprice_ticks': 5,
    'minimum_buy_reprice_ticks': 5,
    'minimum_sell_reprice_ticks': 5,
    'minimum_quote_lifetime_ms': 2000,
    'minimum_sell_quote_lifetime_ms': 2000,
    'buy_stale_reprice_ticks': 25,
    'buy_max_age_ms': 5000,
    'entry_aggr_ticks': 0,
    'exit_aggr_ticks': 0,
    'dynamic_aggression': False,
    'emergency_loss_ticks': 50,
    'stop_loss_ticks': 300,
    'max_aggr_spread_pct': 0.25,
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
