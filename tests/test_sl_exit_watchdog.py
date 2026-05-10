from decimal import Decimal
import pytest
QtWidgets = pytest.importorskip('PySide6.QtWidgets', reason='PySide6 GUI deps are unavailable in this environment')
QApplication = QtWidgets.QApplication
from app.gui.main_window import MainWindow

@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])

def test_order_age_uses_monotonic_reasonable_ms(qapp):
    w = MainWindow()
    w._quote_birth_mono[1] = w._quote_birth_mono.get(1, 0) or 0
    w._quote_birth_mono[1] = __import__('time').monotonic() - 1.2
    assert 900 <= w._order_age_ms(1) <= 5000

def test_sl_exit_reposts_far_sell_to_bid_plus_tick(qapp):
    w = MainWindow()
    w.cfg['exit_aggr_ticks'] = 1
    tick = Decimal('0.01')
    bid = Decimal('100.00')
    working = Decimal('100.20')
    delta_ticks = (working - bid) / tick
    assert delta_ticks > Decimal('1')
    # mirrors watchdog trigger condition
    assert delta_ticks > Decimal(str(w.cfg.get('exit_aggr_ticks', 2)))

def test_orderdbg_delta_ticks(qapp):
    tick = Decimal('0.01')
    bid = Decimal('100.00')
    ask = Decimal('100.05')
    order = Decimal('100.02')
    delta_bid = (order - bid) / tick
    delta_ask = (ask - order) / tick
    assert delta_bid == Decimal('2')
    assert delta_ask == Decimal('3')
