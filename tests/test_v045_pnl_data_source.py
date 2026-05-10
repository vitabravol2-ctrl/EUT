from decimal import Decimal
import pytest

QtWidgets = pytest.importorskip('PySide6.QtWidgets', reason='PySide6 GUI deps are unavailable in this environment')
QApplication = QtWidgets.QApplication

from app.gui.main_window import MainWindow
from app.core.pair_profiles import get_pair_config


@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])


def _window():
    w = MainWindow()
    w._exchange_filters = {'tickSize': '0.01', 'stepSize': '0.00001', 'minQty': '0.00001', 'minNotional': '5'}
    w._pair_config = get_pair_config('BTCU')
    return w


def test_btcu_zero_fee_profitable_cycle(qapp):
    w = _window()
    qty = Decimal('0.05643')
    w._on_buy_fill(qty, Decimal('80794.67'))
    w._on_sell_fill(qty, Decimal('80799.33'))
    assert w._trade_stats['fees'] == Decimal('0')
    assert w._trade_stats['realized_pnl'] > 0
    assert w.ts_realized.text() != ''


def test_inventory_sell_does_not_affect_winrate_or_realized(qapp):
    w = _window()
    before_realized = w._trade_stats['realized_pnl']
    before_wins = w._trade_stats['wins']
    before_cycles = w._trade_stats['cycles']
    w._on_sell_fill(Decimal('0.01'), Decimal('90000'))
    assert w._trade_stats['realized_pnl'] == before_realized
    assert w._trade_stats['wins'] == before_wins
    assert w._trade_stats['cycles'] == before_cycles
    assert w._trade_stats['inventory_sells_count'] == 1


def test_runtime_pnl_equals_trade_stats_pnl(qapp):
    w = _window()
    w._trade_stats['realized_pnl'] = Decimal('1.23')
    w._tick_status()
    assert w.cs_pnl.text() == '1.23000000'


def test_rest_fresh_status_and_not_stale(qapp):
    w = _window()
    w._data_mode = 'REST'
    w._last_market_ts = __import__('time').time()
    w.cfg['market_stale_ms'] = 3000
    w._tick_status()
    assert w._status_badges['DATA'].text() == 'DATA REST OK'
