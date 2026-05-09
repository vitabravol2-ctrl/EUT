from app.core.formatting import format_age_ms


def test_order_age_formatting():
    assert format_age_ms(0) == '00:00'
    assert format_age_ms(65000) == '01:05'
