import pytest

QtCore = pytest.importorskip('PySide6.QtCore')
QCoreApplication = QtCore.QCoreApplication
from app.core.polling_manager import PollingManager


def test_duplicate_start_protection():
    app = QCoreApplication.instance() or QCoreApplication([])
    calls = {'m': 0, 'o': 0, 'b': 0}
    p = PollingManager(lambda: calls.__setitem__('m', calls['m']+1), lambda: calls.__setitem__('o', calls['o']+1), lambda: calls.__setitem__('b', calls['b']+1), 50, 50, 50)
    assert p.start() is True
    assert p.start() is False
    p.stop()
    assert p.running is False
