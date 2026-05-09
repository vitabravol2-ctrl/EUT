import pytest

QtWidgets = pytest.importorskip('PySide6.QtWidgets', reason='PySide6 GUI deps are unavailable in this environment')
QApplication = QtWidgets.QApplication

from app.gui.main_window import MainWindow


@pytest.fixture(scope='module')
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


def test_main_window_smoke(qapp):
    w = MainWindow()
    assert w.styleSheet().strip()
    assert {'Последняя', 'Bid', 'Ask', 'Спред', 'Возраст REST'}.issubset(w.m.keys())
    assert {'USDT свободно', 'USDT заблокировано', 'EURI свободно', 'EURI заблокировано', 'Оценка всего USDT'}.issubset(w.b.keys())
    assert w.buy_btn is not None
    assert w.sell_btn is not None
    assert w.table.columnCount() == 8
