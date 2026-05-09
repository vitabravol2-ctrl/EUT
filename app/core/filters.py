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
