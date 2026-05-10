from app.core.binance_client import BinanceAPIError
from app.core.order_service import OrderService


class _CancelUnknownClient:
    def cancel_order(self, _symbol, _order_id):
        raise BinanceAPIError('HTTP 400: Unknown order sent.', code=-2011, status_code=400)


class _CancelFailClient:
    def cancel_order(self, _symbol, _order_id):
        raise BinanceAPIError('HTTP 500: Server error', code=-1000, status_code=500)


def test_cancel_unknown_order_is_tolerated():
    service = OrderService(_CancelUnknownClient(), 'EURIUSDT')
    resp = service.cancel(123)
    assert resp['orderId'] == 123
    assert resp['status'] == 'UNKNOWN'
    assert '_reaction_ms' in resp


def test_cancel_non_unknown_order_raises():
    service = OrderService(_CancelFailClient(), 'EURIUSDT')
    try:
        service.cancel(123)
        raised = False
    except BinanceAPIError as exc:
        raised = True
        assert exc.code == -1000
    assert raised is True
