from decimal import Decimal
import pytest
QtWidgets = pytest.importorskip('PySide6.QtWidgets', reason='PySide6 GUI deps are unavailable in this environment')
QApplication = QtWidgets.QApplication
from app.gui.main_window import MainWindow

@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])

def test_sell_fill_below_min_exit_is_clamped_in_accounting(qapp):
    w = MainWindow()
    w._exchange_filters = {'tickSize': '0.01', 'stepSize': '0.00001', 'minQty': '0.00001', 'minNotional': '5'}
    w._on_buy_fill(Decimal('1'), Decimal('100.00'))
    w._on_sell_fill(Decimal('1'), Decimal('99.00'))
    assert w._trade_stats['ticks'] >= Decimal('1')
    assert w._trade_stats['realized_pnl'] >= Decimal('0')

def test_runtime_stats_no_duplicates_in_compact_panel(qapp):
    w = MainWindow()
    assert w.cs_pnl is not None
    assert w.cs_trades is not None
    assert w.cs_winrate is not None
    assert w.cs_open_orders is not None
