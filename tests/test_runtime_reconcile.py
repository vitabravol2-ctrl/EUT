from app.core.reconcile import safe_status, should_clear_active_order


def test_safe_status_handles_missing_status_without_crash():
    assert safe_status(None) is None
    assert safe_status({}) is None
    assert safe_status({'status': 'new'}) == 'NEW'


def test_should_not_clear_if_order_is_still_in_open_orders():
    assert should_clear_active_order(10, 'FILLED', {10}) is False


def test_should_clear_when_order_vanished_from_open_orders():
    assert should_clear_active_order(10, 'FILLED', set()) is True
    assert should_clear_active_order(10, None, set()) is True


def test_should_not_clear_when_order_vanished_but_still_working():
    assert should_clear_active_order(10, 'NEW', set()) is False
    assert should_clear_active_order(10, 'PARTIALLY_FILLED', set()) is False


def test_should_not_clear_when_active_and_working():
    assert should_clear_active_order(10, 'NEW', {10}) is False
