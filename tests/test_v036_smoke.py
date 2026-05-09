from decimal import Decimal

from app.core.account_service import AccountService


class DummyClient:
    def __init__(self, payload):
        self.payload = payload

    def get_account(self):
        return self.payload


def test_balance_status_formatting_source_data():
    svc = AccountService(DummyClient({'balances': [{'asset': 'EURI', 'free': '12.34', 'locked': '0.66'}, {'asset': 'USDT', 'free': '5.00', 'locked': '1.00'}]}))
    b = svc.balances(Decimal('1.2'))
    assert b['EURI_free'] == Decimal('12.34')
    assert b['USDT_locked'] == Decimal('1.00')


def test_no_crash_when_balances_empty():
    svc = AccountService(DummyClient({'balances': []}))
    b = svc.balances()
    assert b['EURI_free'] == Decimal('0')


def test_decimal_total_math():
    price = Decimal('1.2345')
    qty = Decimal('8.1000')
    assert (price * qty) == Decimal('9.99945000')
