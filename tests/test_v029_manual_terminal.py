from decimal import Decimal
import time

from app.core.account_service import AccountService
from app.core.market_service import MarketService


class DummyClient:
    def __init__(self):
        self.payload = {
            'balances': [
                {'asset': 'USDT', 'free': '12.9525', 'locked': '1.0000'},
                {'asset': 'EURI', 'free': '147.8', 'locked': '2.2'},
            ]
        }

    def get_account(self):
        return self.payload

    def get_ticker(self, symbol):
        return {'price': '1.1778'}

    def get_book_ticker(self, symbol):
        return {'bidPrice': '1.1777', 'askPrice': '1.1780', 'bidQty': '1', 'askQty': '1'}


def test_estimated_total_includes_euri():
    svc = AccountService(DummyClient())
    data = svc.balances(Decimal('1.1778'))
    assert data['equity_usdt'] == Decimal('190.62250')


def test_tick_calculation_from_ticksize():
    m = MarketService(DummyClient(), 'EURIUSDT')
    m.set_tick_size(Decimal('0.0001'))
    s = m.snapshot()
    assert s['spread'] == Decimal('0.0003')
    assert s['spread_ticks'] == '3'


def test_tick_fallback_when_missing_ticksize():
    m = MarketService(DummyClient(), 'EURIUSDT')
    s = m.snapshot()
    assert s['spread_ticks'] == '-'
    assert s['tick_warning_needed'] is True
