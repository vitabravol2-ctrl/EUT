import pytest

QtWidgets = pytest.importorskip('PySide6.QtWidgets', reason='PySide6 GUI deps are unavailable in this environment')
QApplication = QtWidgets.QApplication

from app.gui.main_window import MainWindow


@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])


def test_main_window_smoke(qapp):
    w = MainWindow()
    assert w.table.columnCount() == 8
    assert w.ts_symbol.text() == w.cfg.get('symbol', 'EURIUSDT')
