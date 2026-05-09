from app.core.config import DEFAULT_CONFIG


def test_default_safety_flags():
    assert DEFAULT_CONFIG['trading_enabled'] is False
    assert DEFAULT_CONFIG['read_only'] is True
