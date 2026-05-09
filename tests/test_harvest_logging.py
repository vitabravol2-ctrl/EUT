import pytest

QtWidgets = pytest.importorskip('PySide6.QtWidgets', reason='PySide6 GUI deps are unavailable in this environment')
QApplication = QtWidgets.QApplication

from app.gui.main_window import MainWindow
from app.core.harvest_readiness import HarvestReadinessResult, HarvestReadinessState


def test_harvest_state_logs_only_on_transition():
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    w._harvest_result = HarvestReadinessResult(HarvestReadinessState.WATCH, 50, ['waiting stability'], True, False, True, True, True, False, 'NONE')
    w._log_harvest_state_if_changed()
    first = len(w.logger.records)
    w._log_harvest_state_if_changed()
    second = len(w.logger.records)
    w._harvest_result = HarvestReadinessResult(HarvestReadinessState.READY, 80, ['ready'], True, True, True, True, True, True, 'BUY')
    w._log_harvest_state_if_changed()
    third = len(w.logger.records)
    assert first == second
    assert third == second + 1
