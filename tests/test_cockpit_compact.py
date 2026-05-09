import pytest

QtWidgets = pytest.importorskip('PySide6.QtWidgets', reason='PySide6 GUI deps are unavailable in this environment')
QApplication = QtWidgets.QApplication

from app.gui.main_window import MainWindow
from app.core.config import load_config


@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])


def test_status_strip_includes_market_badges(qapp):
    w = MainWindow()
    for key in ['REST', 'ACCOUNT', 'PRIVATE', 'TRADING', 'LATENCY', 'HARVEST', 'FSM', 'LAST', 'BID', 'ASK', 'SPREAD', 'TICKS']:
        assert key in w._status_badges


def test_old_market_panel_removed_and_no_root_scrollarea(qapp):
    w = MainWindow()
    assert 'Market Summary' not in [g.title() for g in w.findChildren(QtWidgets.QGroupBox)]
    roots = [c for c in w.findChildren(QtWidgets.QScrollArea) if c.parent() == w.centralWidget()]
    assert roots == []


def test_trade_settings_save_load(qapp):
    w = MainWindow()
    w.trade_mode.setCurrentText('OBSERVER')
    w.min_spread_ticks.setText('3')
    w.stable_ms.setText('3500')
    w.max_order_usdt.setText('15')
    w.max_active_orders.setText('2')
    w.risk_guard_enabled.setChecked(True)
    w.save_trade_settings()
    cfg = load_config()
    assert cfg['trade_mode'] == 'OBSERVER'
    assert cfg['min_spread_ticks'] == 3
    assert cfg['risk_guard_enabled'] is True


def test_manual_place_cancel_still_callable(qapp):
    w = MainWindow()
    w.place('BUY')
    w.cancel_selected()
    w.cancel_all()
