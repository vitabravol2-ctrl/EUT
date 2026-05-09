import pytest
from decimal import Decimal

QtWidgets = pytest.importorskip('PySide6.QtWidgets', reason='PySide6 GUI deps are unavailable in this environment')
QApplication = QtWidgets.QApplication

from app.gui.main_window import MainWindow


@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])


def test_status_badge_mapping(qapp):
    w = MainWindow()
    w._set_status_badge('Публичный REST', 'OK')
    assert 'REST ● OK' in w.s['Публичный REST'].text()
    w._set_status_badge('Задержка', 'WARN 1000ms')
    assert 'WARN' in w.s['Задержка'].text()


def test_compact_market_and_balance_summary(qapp):
    w = MainWindow()
    for k in ['Последняя', 'Bid', 'Ask', 'Спред', 'Тики', 'Lifetime', 'Stable', 'Latency']:
        assert k in w.m
    for k in ['USDT total', 'EURI total', 'Оценка всего USDT']:
        assert k in w.b


def test_quick_fill_buttons_and_qty_helper(qapp):
    w = MainWindow()
    w.m['Bid'].setText('1.10000000')
    w.m['Ask'].setText('1.20000000')
    w._fill_price_bid()
    assert w.price.text() == '1.10000000'
    w._fill_price_ask()
    assert w.price.text() == '1.20000000'
    w.b['EURI свободно'].setText('5.25000000')
    w._fill_qty_max_euri()
    assert w.qty.text() == '5.25000000'
    w._fill_qty_for_10_usdt()
    assert Decimal(w.qty.text()) > 0


def test_no_root_scrollarea(qapp):
    w = MainWindow()
    roots = [c for c in w.findChildren(QtWidgets.QScrollArea) if c.parent() == w.centralWidget()]
    assert roots == []
