from app.core.filters import normalize_price, normalize_qty


def test_normalize_price():
    assert normalize_price('1.17809', '0.0001') == '1.1780'


def test_normalize_qty():
    assert normalize_qty('13.57', '0.1') == '13.5'
