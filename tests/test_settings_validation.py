from app.core.settings_validation import validate_settings


def test_settings_validation_empty_keys():
    ok, msgs = validate_settings({'api_key': '', 'api_secret': '', 'testnet': False, 'read_only': True, 'trading_enabled': False})
    assert not ok
    assert any('API key is empty' in m for m in msgs)


def test_settings_validation_conflict_warning():
    ok, msgs = validate_settings({'api_key': 'k', 'api_secret': 's', 'testnet': True, 'read_only': True, 'trading_enabled': True})
    assert ok
    assert any('conflicts' in m for m in msgs)
