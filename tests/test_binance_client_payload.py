from app.core.binance_client import BinanceClient


def test_limit_maker_payload_uses_strings(monkeypatch):
    captured = {}

    def fake_request(self, method, path, *, params=None, signed=False, retries=1):
        captured['params'] = params
        return {'orderId': 1}

    monkeypatch.setattr(BinanceClient, '_request', fake_request)
    client = BinanceClient('k', 's')
    client.create_limit_maker_order('EURIUSDT', 'BUY', '16.98', '1.1775')

    assert isinstance(captured['params']['quantity'], str)
    assert isinstance(captured['params']['price'], str)
