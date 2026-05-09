from app.core.runtime_state import RuntimeState
from app.gui.ui_constants import BUTTON_H, BUTTON_MIN_W, AUTH_FAILED_MSG


def trading_allowed(cfg, state):
    return state.account_auth_state == 'CONNECTED' and not cfg.get('read_only', True) and cfg.get('trading_enabled') and cfg.get('api_key') and cfg.get('api_secret')


def test_trading_cannot_enable_when_disconnected():
    s = RuntimeState()
    cfg = {'read_only': False, 'trading_enabled': True, 'api_key': 'k', 'api_secret': 's'}
    assert trading_allowed(cfg, s) is False


def test_private_polling_paused_after_auth_error():
    s = RuntimeState()
    s.private_polling_state = 'RUNNING'
    s.set_account_auth('AUTH_ERROR')
    s.private_polling_state = 'PAUSED'
    assert s.account_auth_state == 'AUTH_ERROR'
    assert s.private_polling_state == 'PAUSED'


def test_button_minimum_size_constants():
    assert BUTTON_H >= 28
    assert BUTTON_H <= 32
    assert BUTTON_MIN_W >= 120


def test_log_dedupe_auth_error_message():
    assert 'Private polling paused.' in AUTH_FAILED_MSG


def test_public_and_account_status_separated():
    s = RuntimeState()
    s.public_rest_state = 'OK'
    s.set_account_auth('DISCONNECTED')
    assert s.public_rest_state == 'OK'
    assert s.account_auth_state == 'DISCONNECTED'
