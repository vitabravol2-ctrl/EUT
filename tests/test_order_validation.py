from app.core.filters import validate_order


def test_validate_order_ok():
    ok, _ = validate_order('1.1780', '10.0', tick_size='0.0001', step_size='0.1', min_qty='0.1', min_notional='5')
    assert ok


def test_validate_order_min_notional_fail():
    ok, msg = validate_order('1.1780', '1.0', tick_size='0.0001', step_size='0.1', min_qty='0.1', min_notional='5')
    assert not ok
    assert 'minNotional' in msg
