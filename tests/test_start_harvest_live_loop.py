import pytest

QtWidgets = pytest.importorskip('PySide6.QtWidgets', reason='PySide6 GUI deps are unavailable in this environment')
QApplication = QtWidgets.QApplication
QMessageBox = QtWidgets.QMessageBox

from app.gui.main_window import MainWindow
from app.core.harvest_readiness import ReadinessState
from app.core.harvest_cycle import CycleState


@pytest.fixture
def window(monkeypatch):
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    w._private_ok = True
    w._balances = {'risk_blocked': False}
    w._spread_metrics = type('S', (), {'state': type('R', (), {'readiness': ReadinessState.READY})()})()
    w._fill_observation = type('F', (), {'fill_possible': True})()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args, **kwargs: QMessageBox.Yes)
    return w


def test_start_button_connected(window):
    assert window.start_harvest_btn is not None
    assert window.start_harvest_btn.text() == 'START HARVEST'


def test_start_harvest_no_silent_return(window):
    window.start_harvest()
    messages = [r.message for r in window.logger.records]
    assert '[LIVE] start clicked' in messages
    assert any(m.startswith('[LIVE] runtime started') or m.startswith('[RISK] blocked:') for m in messages)


def test_start_sets_live_running(window):
    window.start_harvest()
    assert window._live_running is True
    assert window._runtime_active is True
    assert window._cycle.state == CycleState.WAIT_READY


def test_tick_calls_run_live_cycle_when_live(window, monkeypatch):
    called = {'n': 0}

    def fake_run():
        called['n'] += 1

    monkeypatch.setattr(window, '_run_live_cycle', fake_run)
    window._live_running = True
    window._tick_status()
    assert called['n'] >= 1
