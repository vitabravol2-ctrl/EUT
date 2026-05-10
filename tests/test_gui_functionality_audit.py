import pytest

QtWidgets = pytest.importorskip('PySide6.QtWidgets', reason='PySide6 GUI deps are unavailable in this environment')
QApplication = QtWidgets.QApplication
QMessageBox = QtWidgets.QMessageBox

from app.gui.main_window import MainWindow


@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(monkeypatch, qapp):
    monkeypatch.setattr(MainWindow, '_init_services', lambda self: None)
    monkeypatch.setattr(MainWindow, '_startup_connect_flow', lambda self: None)
    w = MainWindow()
    return w


def test_start_button_signal_connected(window):
    assert window.start_harvest_btn.receivers(window.start_harvest_btn.clicked) > 0


def test_start_click_logs_gui_and_live(window, monkeypatch):
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.Yes)
    window._private_ok = True
    logs = []
    monkeypatch.setattr(window.logger, 'log', lambda lvl, msg: logs.append(msg))
    window.start_harvest()
    assert '[GUI] START clicked' in logs
    assert '[LIVE] start clicked' in logs
    assert '[GUI] confirmation yes' in logs
    assert '[LIVE] runtime started' in logs


def test_stop_click_stops_runtime(window, monkeypatch):
    logs = []
    monkeypatch.setattr(window.logger, 'log', lambda lvl, msg: logs.append(msg))
    window._live_running = True
    window.stop_harvest()
    assert window._live_running is False
    assert '[LIVE] stopped' in logs


def test_status_strip_runtime_stats_same_source(window):
    window._private_ok = True
    window._last_market_source = 'REST'
    window._last_market_ts = 0
    window._spread_metrics = None
    window._update_status_strip()
    window._update_runtime_stats_panel()
    assert window.cs_data_source.text() == window._ui_state['data_source']
    assert int(window.cs_open_orders.text()) == window._ui_state['orders_count']


def test_cancel_selected_without_selection_logs_risk(window, monkeypatch):
    logs = []
    monkeypatch.setattr(window.logger, 'log', lambda lvl, msg: logs.append(msg))
    window._selected_order_id = None
    window.cancel_selected()
    assert '[RISK] blocked: no order selected' in logs


def test_theme_has_button_states(window):
    ss = window.styleSheet()
    assert 'QPushButton:hover' in ss
    assert 'QPushButton:pressed' in ss
    assert 'QPushButton:disabled' in ss
