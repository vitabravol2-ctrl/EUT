from __future__ import annotations


TERMINAL_ORDER_STATUSES = {'FILLED', 'CANCELED', 'REJECTED', 'EXPIRED'}
LIVE_ORDER_STATUSES = {'NEW', 'PARTIALLY_FILLED'}


def safe_status(payload: dict | None) -> str | None:
    if not payload:
        return None
    status = payload.get('status')
    if status is None:
        return None
    return str(status).upper()


def should_clear_active_order(active_order_id: int | None, status: str | None, open_order_ids: set[int]) -> bool:
    if not active_order_id:
        return False
    if active_order_id in open_order_ids:
        return False
    if status in LIVE_ORDER_STATUSES:
        return False
    return status in TERMINAL_ORDER_STATUSES or status is None
