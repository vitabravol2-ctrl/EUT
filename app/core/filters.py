from __future__ import annotations

from decimal import Decimal, ROUND_DOWN


def _d(value: str | float | Decimal) -> Decimal:
    return Decimal(str(value))


def _decimals_from_step(step: Decimal) -> int:
    normalized = step.normalize()
    exponent = normalized.as_tuple().exponent
    return -exponent if exponent < 0 else 0


def floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def floor_to_tick(price: Decimal, tick: Decimal) -> Decimal:
    return (price / tick).to_integral_value(rounding=ROUND_DOWN) * tick


def format_decimal_for_step(value: Decimal, step: Decimal) -> str:
    floored = floor_to_step(value, step)
    decimals = _decimals_from_step(step)
    return format(floored, f'.{decimals}f')


def format_decimal_for_tick(price: Decimal, tick: Decimal) -> str:
    floored = floor_to_tick(price, tick)
    decimals = _decimals_from_step(tick)
    return format(floored, f'.{decimals}f')


def normalize_price(price: str | float, tick_size: str) -> str:
    return format_decimal_for_tick(_d(price), _d(tick_size))


def normalize_qty(qty: str | float, step_size: str) -> str:
    return format_decimal_for_step(_d(qty), _d(step_size))


def extract_symbol_filters(exchange_info: dict) -> dict[str, str]:
    symbols = exchange_info.get('symbols') or []
    symbol_data = symbols[0] if symbols else {}
    filters = {f.get('filterType'): f for f in (symbol_data.get('filters') or []) if isinstance(f, dict)}

    price_filter = filters.get('PRICE_FILTER', {})
    lot_size = filters.get('LOT_SIZE', {})
    notional_filter = filters.get('NOTIONAL', {}) or filters.get('MIN_NOTIONAL', {})

    tick_size = str(price_filter.get('tickSize', '0'))
    step_size = str(lot_size.get('stepSize', '0'))
    min_qty = str(lot_size.get('minQty', '0'))
    max_qty = str(lot_size.get('maxQty', '0'))
    min_notional = str(notional_filter.get('minNotional', '0'))
    return {
        'tickSize': tick_size,
        'stepSize': step_size,
        'minQty': min_qty,
        'maxQty': max_qty,
        'minNotional': min_notional,
    }


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
    filters = extract_symbol_filters(exchange_info)
    return validate_order(
        price,
        qty,
        tick_size=filters['tickSize'],
        step_size=filters['stepSize'],
        min_qty=filters['minQty'],
        min_notional=filters['minNotional'],
    )
