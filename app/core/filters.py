from __future__ import annotations

from decimal import Decimal, ROUND_DOWN


def _d(value: str | float) -> Decimal:
    return Decimal(str(value))


def normalize_price(price: str | float, tick_size: str) -> str:
    p = _d(price)
    t = _d(tick_size)
    return str((p / t).to_integral_value(rounding=ROUND_DOWN) * t)


def normalize_qty(qty: str | float, step_size: str) -> str:
    q = _d(qty)
    s = _d(step_size)
    return str((q / s).to_integral_value(rounding=ROUND_DOWN) * s)


def _extract_filter_values(exchange_info: dict) -> tuple[str, str, str, str]:
    symbols = exchange_info.get('symbols') or []
    symbol_data = symbols[0] if symbols else {}
    filters = {f.get('filterType'): f for f in (symbol_data.get('filters') or []) if isinstance(f, dict)}

    price_filter = filters.get('PRICE_FILTER', {})
    lot_size = filters.get('LOT_SIZE', {})
    notional_filter = filters.get('NOTIONAL', {}) or filters.get('MIN_NOTIONAL', {})

    tick_size = str(price_filter.get('tickSize', '0'))
    step_size = str(lot_size.get('stepSize', '0'))
    min_qty = str(lot_size.get('minQty', '0'))
    min_notional = str(notional_filter.get('minNotional', '0'))
    return tick_size, step_size, min_qty, min_notional


def validate_order(price: str, qty: str, *, tick_size: str, step_size: str, min_qty: str, min_notional: str) -> tuple[bool, str]:
    p = _d(price)
    q = _d(qty)
    if p <= 0 or q <= 0:
        return False, 'price/qty must be > 0'
    if _d(normalize_price(price, tick_size)) != p:
        return False, 'price not aligned to tickSize'
    if _d(normalize_qty(qty, step_size)) != q:
        return False, 'qty not aligned to stepSize'
    if q < _d(min_qty):
        return False, 'qty below minQty'
    if p * q < _d(min_notional):
        return False, 'notional below minNotional'
    if p * q > Decimal('1000000'):
        return False, 'notional too large'
    return True, 'ok'


def validate_order_from_exchange_info(price: str, qty: str, exchange_info: dict) -> tuple[bool, str]:
    tick_size, step_size, min_qty, min_notional = _extract_filter_values(exchange_info)
    return validate_order(price, qty, tick_size=tick_size, step_size=step_size, min_qty=min_qty, min_notional=min_notional)
