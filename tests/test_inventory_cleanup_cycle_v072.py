import pytest
from decimal import Decimal

QtWidgets = pytest.importorskip('PySide6.QtWidgets', reason='PySide6 GUI deps are unavailable in this environment')
QApplication = QtWidgets.QApplication

from app.gui.main_window import MainWindow
from app.core.spread_stability_engine import ReadinessState


class _DummyOrders:
    def __init__(self):
        self.placed = []

    def order_status(self, _order_id):
        return {'status': 'NEW', 'executedQty': '0', 'price': '1.1002'}

    def place_limit_maker(self, side, qty, price):
        self.placed.append((side, qty, price))
        return {'orderId': len(self.placed)}

    def cancel(self, _order_id):
        return {'status': 'CANCELED'}


@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])


def _ready_window():
    w = MainWindow()
    w._live_running = True
    w._private_ok = True
    w.cfg['enable_inventory_cleanup'] = False
    w._balances = {'USDT_free': '1000', 'EURI_free': '5', 'EURI_locked': '0'}
    w._last_market_snapshot = {'bid': '1.1000', 'ask': '1.1002'}
    w._spread_metrics = type('M', (), {'state': type('S', (), {'readiness': ReadinessState.READY})()})()
    w._fill_observation = type('F', (), {'fill_possible': True})()
    w._exchange_filters = {'tickSize': '0.0001', 'stepSize': '0.01', 'minQty': '0.01', 'minNotional': '5'}
    w._require_exchange_filters = lambda: True
    w.orders = _DummyOrders()
    w.refresh_orders = lambda force=False: None
    return w


def test_inventory_cleanup_disabled_does_not_sell_old_base(qapp):
    w = _ready_window()
    w._cycle.open_position_qty = Decimal('0')
    w._run_live_cycle()
    assert all(side != 'SELL' for side, _, _ in w.orders.placed)


def test_buy_fill_places_sell_for_exact_position_qty(qapp):
    w = _ready_window()
    w._cycle.open_position_qty = Decimal('2.75')
    w._run_live_cycle()
    sell = next((o for o in w.orders.placed if o[0] == 'SELL'), None)
    assert sell is not None
    assert Decimal(sell[1]) == Decimal('2.75')


def test_sell_fill_closes_cycle_and_returns_flat(qapp):
    w = _ready_window()
    w._cycle.open_position_qty = Decimal('1')
    w._cycle.buy_filled_qty = Decimal('1')
    w._cycle.buy_avg_price = Decimal('1.1')
    w._cycle.sell_order_id = 11
    w._orders_by_id = {11: {'orderId': 11, 'origQty': '1', 'executedQty': '1', 'price': '1.1010', 'status': 'FILLED'}}
    w._last_open_orders = []
    w.orders.order_status = lambda _oid: {'status': 'FILLED', 'executedQty': '1', 'price': '1.1010'}
    w._run_live_cycle()
    assert w._cycle.open_position_qty <= Decimal('0.01')
    assert w._cycle.sell_order_id is None


def test_inventory_sell_not_counted_as_closed_trade(qapp):
    from app.core.trade_ledger import TradeLedger
    l = TradeLedger()
    l.record_sell(Decimal('2'), Decimal('1.2'), tick_size=Decimal('0.0001'))
    s = l.snapshot()
    assert s['completed_cycles'] == 0
    assert s['inventory_sell_qty'] == Decimal('2')


def test_no_stale_ts_label_warnings(qapp):
    w = _ready_window()
    w._update_runtime_stats_from_ledger()
    assert not any('[GUI] stale label ignored key=ts_' in rec.message for rec in w.logger._records)
