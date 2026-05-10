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
    maker_fee_rate: float
    taker_fee_rate: float
    ws_stale_ms: int
    rest_validate_sec: int
    max_ws_rest_drift_ticks: int
    minimum_reprice_ticks: int
    minimum_buy_reprice_ticks: int
    minimum_sell_reprice_ticks: int
    minimum_quote_lifetime_ms: int
    minimum_sell_quote_lifetime_ms: int
    max_reprice_per_sec: int


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
        maker_fee_rate=0.0,
        taker_fee_rate=0.0,
        ws_stale_ms=5000,
        rest_validate_sec=10,
        max_ws_rest_drift_ticks=2,
        minimum_reprice_ticks=1,
        minimum_buy_reprice_ticks=1,
        minimum_sell_reprice_ticks=1,
        minimum_quote_lifetime_ms=3000,
        minimum_sell_quote_lifetime_ms=3000,
        max_reprice_per_sec=1,
    ),
    'BTCU': PairConfig(
        symbol='BTCU',
        base_asset='BTC',
        quote_asset='U',
        profile='FAST_COMPETITIVE',
        default_spread_ticks=1,
        default_stable_ms=500,
        aggressive_reprice=True,
        top_check_interval_sec=0.15,
        top_hold_patience_sec=0.75,
        quote_refresh_interval_sec=0.80,
        maker_fee_rate=0.0,
        taker_fee_rate=0.0,
        ws_stale_ms=1500,
        rest_validate_sec=3,
        max_ws_rest_drift_ticks=3,
        minimum_reprice_ticks=5,
        minimum_buy_reprice_ticks=25,
        minimum_sell_reprice_ticks=20,
        minimum_quote_lifetime_ms=2000,
        minimum_sell_quote_lifetime_ms=4000,
        max_reprice_per_sec=2,
    ),
}

KNOWN_QUOTES = ('USDT', 'USDC', 'BUSD', 'FDUSD', 'TUSD', 'TRY', 'EUR', 'USD', 'BTC', 'ETH', 'BNB', 'U')


def split_symbol_assets(symbol: str) -> tuple[str, str]:
    key = str(symbol or '').upper().strip()
    if not key:
        return 'EURI', 'USDT'
    for quote in KNOWN_QUOTES:
        if key.endswith(quote) and len(key) > len(quote):
            return key[:-len(quote)], quote
    if len(key) >= 2:
        return key[:-1], key[-1]
    return key, 'USDT'


def get_pair_config(symbol: str) -> PairConfig:
    key = str(symbol or 'EURIUSDT').upper()
    if key in PAIR_REGISTRY:
        return PAIR_REGISTRY[key]
    base_asset, quote_asset = split_symbol_assets(key)
    default = PAIR_REGISTRY['EURIUSDT']
    return PairConfig(
        symbol=key,
        base_asset=base_asset,
        quote_asset=quote_asset,
        profile=default.profile,
        default_spread_ticks=default.default_spread_ticks,
        default_stable_ms=default.default_stable_ms,
        aggressive_reprice=default.aggressive_reprice,
        top_check_interval_sec=default.top_check_interval_sec,
        top_hold_patience_sec=default.top_hold_patience_sec,
        quote_refresh_interval_sec=default.quote_refresh_interval_sec,
        maker_fee_rate=default.maker_fee_rate,
        taker_fee_rate=default.taker_fee_rate,
        ws_stale_ms=default.ws_stale_ms,
        rest_validate_sec=default.rest_validate_sec,
        max_ws_rest_drift_ticks=default.max_ws_rest_drift_ticks,
        minimum_reprice_ticks=default.minimum_reprice_ticks,
        minimum_buy_reprice_ticks=default.minimum_buy_reprice_ticks,
        minimum_sell_reprice_ticks=default.minimum_sell_reprice_ticks,
        minimum_quote_lifetime_ms=default.minimum_quote_lifetime_ms,
        minimum_sell_quote_lifetime_ms=default.minimum_sell_quote_lifetime_ms,
        max_reprice_per_sec=default.max_reprice_per_sec,
    )


def list_pairs() -> list[str]:
    return list(PAIR_REGISTRY.keys())
