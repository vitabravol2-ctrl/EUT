import pytest

QtWidgets = pytest.importorskip('PySide6.QtWidgets', reason='PySide6 GUI deps are unavailable in this environment')
QApplication = QtWidgets.QApplication

from app.gui.main_window import MainWindow, ManualOrderDialog


@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])


def test_status_strip_contains_critical_items(qapp):
    w = MainWindow()
    assert set(w._status_badges.keys()) == {'SYSTEM', 'TRADING', 'EURI', 'USDT', 'SPREAD', 'HARVEST', 'ORDERS', 'RISK'}


def test_manual_dialog_market_helpers_and_decimal_total(qapp):
    w = MainWindow()
    w._last_market_snapshot = {'bid': '1.10000000', 'ask': '1.20000000'}
    d = ManualOrderDialog(w)
    d._ask()
    d._q10()
    assert d.price.text() == '1.20000000'
    assert d.qty.text() != '0'
    d._calc()
    assert d.total.text() != '0.00000000'
