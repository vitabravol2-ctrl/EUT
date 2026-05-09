from decimal import Decimal

from app.core.filters import format_decimal_for_step, format_decimal_for_tick


def test_step_precision_001_forces_two_decimals():
    assert format_decimal_for_step(Decimal('16.985138'), Decimal('0.01')) == '16.98'


def test_step_precision_1_drops_fraction():
    assert format_decimal_for_step(Decimal('16.98'), Decimal('1')) == '16'


def test_step_precision_0001():
    assert format_decimal_for_step(Decimal('16.985138'), Decimal('0.001')) == '16.985'


def test_tick_precision_0001():
    assert format_decimal_for_tick(Decimal('1.17756'), Decimal('0.0001')) == '1.1775'
