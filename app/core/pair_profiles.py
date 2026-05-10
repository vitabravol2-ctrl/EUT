from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PairProfileName = Literal['SLOW_STABLE', 'FAST_COMPETITIVE']


@dataclass(frozen=True)
class PairConfig:
    symbol: str
    base_asset: str
    quote_asset: str
    profile: PairProfileName
    default_spread_ticks: int
    default_stable_ms: int
    aggressive_reprice: bool
    top_check_interval_sec: float
    top_hold_patience_sec: float
    quote_refresh_interval_sec: float


PAIR_REGISTRY: dict[str, PairConfig] = {
    'EURIUSDT': PairConfig(
        symbol='EURIUSDT',
        base_asset='EURI',
        quote_asset='USDT',
        profile='SLOW_STABLE',
        default_spread_ticks=1,
        default_stable_ms=3000,
        aggressive_reprice=False,
        top_check_interval_sec=0.40,
        top_hold_patience_sec=2.00,
        quote_refresh_interval_sec=1.50,
    ),
    'BTCU': PairConfig(
        symbol='BTCU',
        base_asset='BTC',
        quote_asset='USDT',
        profile='FAST_COMPETITIVE',
        default_spread_ticks=1,
        default_stable_ms=500,
        aggressive_reprice=True,
        top_check_interval_sec=0.15,
        top_hold_patience_sec=0.75,
        quote_refresh_interval_sec=0.80,
    ),
}


def get_pair_config(symbol: str) -> PairConfig:
    key = str(symbol or 'EURIUSDT').upper()
    return PAIR_REGISTRY.get(key, PAIR_REGISTRY['EURIUSDT'])


def list_pairs() -> list[str]:
    return list(PAIR_REGISTRY.keys())
