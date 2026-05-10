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
    assert any(msg.startswith('[GUI] confirmation result=') for msg in logs)
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


def test_start_confirmation_yes_calls_start_runtime(window, monkeypatch):
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.Yes)
    window._private_ok = True
    calls = []
    monkeypatch.setattr(window, '_start_live_runtime', lambda: calls.append('start'))
    window.start_harvest()
    assert calls == ['start']


def test_start_confirmation_no_logs_no(window, monkeypatch):
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.No)
    window._private_ok = True
    logs = []
    monkeypatch.setattr(window.logger, 'log', lambda lvl, msg: logs.append(msg))
    window.start_harvest()
    assert '[GUI] confirmation no' in logs


def test_all_data_button_calls_handler(window, monkeypatch):
    calls = []
    monkeypatch.setattr(window, 'show_all_data', lambda: calls.append('all_data'))
    window.all_data_button.clicked.emit()
    assert calls == ['all_data']


def test_all_gui_actions_have_direct_refs(window):
    assert window.start_button is not None
    assert window.stop_button is not None
    assert window.manual_order_button is not None
    assert window.cancel_selected_button is not None
    assert window.cancel_all_button is not None
    assert window.all_data_button is not None
    assert window.settings_button is not None
    assert window.edit_settings_button is not None


def test_gui_action_exceptions_are_logged(window, monkeypatch):
    logs = []
    monkeypatch.setattr(window.logger, 'log', lambda lvl, msg: logs.append(msg))
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom')))
    window._private_ok = True
    window.start_harvest()
    assert any('[ERROR] GUI action failed action=START' in msg for msg in logs)
