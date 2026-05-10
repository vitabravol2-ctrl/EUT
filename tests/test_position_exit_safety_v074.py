from decimal import Decimal
import pytest

QtWidgets = pytest.importorskip('PySide6.QtWidgets', reason='PySide6 GUI deps are unavailable in this environment')
QApplication = QtWidgets.QApplication

from app.gui.main_window import MainWindow


@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])


def test_position_exit_ignores_exposure_cap(qapp):
    w = MainWindow()
    qty = w._compute_position_exit_sell_qty(Decimal('0.01229000'), Decimal('0.00001000'))
    exposure_limited_qty = Decimal('0.01181000')
    assert qty == Decimal('0.01229000')
    assert qty > exposure_limited_qty


def test_position_sell_equals_full_position_qty(qapp):
    w = MainWindow()
    position_qty = Decimal('0.01229000')
    step = Decimal('0.00001000')
    sell_qty = w._compute_position_exit_sell_qty(position_qty, step)
    assert sell_qty == position_qty
    assert w._ensure_position_exit_invariant(sell_qty, position_qty, step) == position_qty


def test_sl_confirmed_without_sell_forces_emergency_exit(qapp):
    w = MainWindow()

    class StubOrders:
        def __init__(self):
            self.called = False
        def place_market(self, side: str, qty: str):
            self.called = True
            assert side == 'SELL'
            assert qty == '0.01229000'
            return {'orderId': 777}

    stub = StubOrders()
    w.orders = stub
    resp = w.orders.place_market('SELL', f"{Decimal('0.01229000'):.8f}")
    assert stub.called is True
    assert resp['orderId'] == 777


def test_long_open_cannot_exist_without_exit_order(qapp):
    w = MainWindow()
    position_qty = Decimal('0.01229000')
    step = Decimal('0.00001000')
    sell_qty = w._compute_position_exit_sell_qty(position_qty, step)
    assert position_qty > 0
    assert sell_qty > 0


def test_exit_sell_notional_can_exceed_buy_cap(qapp):
    w = MainWindow()
    ask = Decimal('1.10')
    position_qty = Decimal('0.01229000')
    max_buy_exposure = Decimal('0.01000000')
    sell_qty = w._compute_position_exit_sell_qty(position_qty, Decimal('0.00001000'))
    assert sell_qty * ask > max_buy_exposure
