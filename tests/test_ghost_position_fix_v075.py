from decimal import Decimal
import pytest

QtWidgets = pytest.importorskip('PySide6.QtWidgets', reason='PySide6 GUI deps are unavailable in this environment')
QApplication = QtWidgets.QApplication

from app.gui.main_window import MainWindow
from app.core.harvest_cycle import CycleState


@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])


def test_market_sell_fill_updates_ledger_price(qapp):
    w = MainWindow()
    status = {'executedQty': '2', 'cummulativeQuoteQty': '2.50', 'price': '0'}
    assert w._extract_sell_fill_price(status, Decimal('1.20')) == Decimal('1.25')


def test_sell_filled_forces_position_close(qapp):
    w = MainWindow()
    w._cycle.open_position_qty = Decimal('1.5')
    w._cycle.sell_order_id = 123
    w._finalize_closed_position(123, 'TEST_FORCE')
    assert w._cycle.open_position_qty == Decimal('0')
    assert w._cycle.sell_order_id is None
    assert w._cycle.state == CycleState.WAIT_READY


def test_closed_event_emitted_once(qapp):
    w = MainWindow()
    w._cycle.open_position_qty = Decimal('1')
    w._finalize_closed_position(777, 'TEST_ONCE_A')
    closed_count_a = len([r for r in w.logger._records if '[CYCLE] CLOSED' in r.message])
    w._cycle.open_position_qty = Decimal('1')
    w._finalize_closed_position(777, 'TEST_ONCE_B')
    closed_count_b = len([r for r in w.logger._records if '[CYCLE] CLOSED' in r.message])
    assert closed_count_a == 1
    assert closed_count_b == 1


def test_market_sell_pnl_not_negative_full_notional(qapp):
    w = MainWindow()
    w._on_buy_fill(Decimal('1'), Decimal('1.00'))
    w._on_sell_fill(Decimal('1'), Decimal('1.01'))
    snap = w._trade_ledger.snapshot()
    assert snap['last_closed_trade_pnl'] > Decimal('0')
    assert snap['last_closed_trade_ticks'] > Decimal('0')
