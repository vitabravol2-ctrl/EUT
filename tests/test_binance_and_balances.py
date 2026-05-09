from app.core.account_service import AccountService
from app.core.binance_client import BinanceAPIError, normalize_binance_error


class DummyClient:
    def __init__(self, payload):
        self.payload = payload

    def get_account(self):
        return self.payload


def test_error_normalization_auth():
    exc = BinanceAPIError('bad', code=-2015, status_code=401)
    assert 'Binance auth failed' in normalize_binance_error(exc)


def test_error_normalization_timestamp():
    exc = BinanceAPIError('bad', code=-1021)
    assert 'timestamp out of sync' in normalize_binance_error(exc)


def test_balance_parsing_missing_euri():
    svc = AccountService(DummyClient({'balances': [{'asset': 'USDT', 'free': '10', 'locked': '1'}]}))
    b = svc.balances()
    assert b['EURI_free'] == 0.0
    assert b['USDT_locked'] == 1.0


def test_estimated_total_formula_sample():
    b = {'USDT_free': 10.0, 'USDT_locked': 2.0, 'EURI_free': 5.0, 'EURI_locked': 1.0}
    last_price = 1.2
    est = b['USDT_free'] + b['USDT_locked'] + (b['EURI_free'] + b['EURI_locked']) * last_price
    assert est == 19.2
