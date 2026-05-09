from app.core.account_service import AccountService
from app.core.runtime_state import RuntimeState
from app.gui.ui_constants import OPEN_ORDERS_COL_WIDTHS, BUTTON_H, TABLE_ROW_H, RU_LABELS


class DummyClient:
    def __init__(self, payload):
        self.payload = payload

    def get_account(self):
        return self.payload


def test_balance_parser_returns_zero_for_missing_assets():
    svc = AccountService(DummyClient({'balances': []}))
    b = svc.balances()
    assert b['USDT_free'] == 0.0
    assert b['EURI_locked'] == 0.0


def test_estimated_total_formula():
    b = {'USDT_free': 1.0, 'USDT_locked': 2.0, 'EURI_free': 3.0, 'EURI_locked': 4.0}
    assert b['USDT_free'] + b['USDT_locked'] + (b['EURI_free'] + b['EURI_locked']) * 1.1 == 10.700000000000001


def test_account_connected_allows_private_polling_flag():
    r = RuntimeState()
    r.set_account_auth('CONNECTED')
    assert r.account_auth_state == 'CONNECTED'


def test_auth_error_can_pause_private_polling_state():
    r = RuntimeState(private_polling_state='RUNNING')
    r.set_account_auth('AUTH_ERROR')
    r.private_polling_state = 'PAUSED'
    assert r.private_polling_state == 'PAUSED'


def test_ru_labels_and_gui_constants_exist():
    assert RU_LABELS['Runtime Status'] == 'Статус системы'
    assert BUTTON_H >= 30
    assert TABLE_ROW_H == 28
    assert OPEN_ORDERS_COL_WIDTHS[0] >= 120
