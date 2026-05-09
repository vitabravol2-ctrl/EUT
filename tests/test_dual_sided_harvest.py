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
        return {'status': 'NEW', 'executedQty': '0', 'price': '1.0000'}

    def place_limit_maker(self, side, qty, price):
        self.placed.append((side, qty, price))
        return {'orderId': len(self.placed)}

    def cancel(self, _order_id):
        return {'status': 'CANCELED'}


class _AlwaysMissingOrders(_DummyOrders):
    def __init__(self):
        super().__init__()
        self.status_calls = 0

    def order_status(self, _order_id):
        self.status_calls += 1
        return {'status': 'NEW', 'executedQty': '0', 'price': '1.0000'}


@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])


def _ready_window():
    w = MainWindow()
    w._live_running = True
    w._private_ok = True
    w._balances = {'USDT_free': '1000', 'EURI_free': '0'}
    w._last_market_snapshot = {'bid': '1.1000', 'ask': '1.1002'}
    w._spread_metrics = type('M', (), {'state': type('S', (), {'readiness': ReadinessState.READY})()})()
    w._fill_observation = type('F', (), {'fill_possible': True})()
    w._exchange_filters = {'tickSize': '0.0001', 'stepSize': '0.01'}
    w._require_exchange_filters = lambda: True
    w.orders = _DummyOrders()
    w.refresh_orders = lambda force=False: None
    return w


def test_no_global_block_on_open_orders_for_buy(qapp):
    w = _ready_window()
    w._last_open_orders = [{'orderId': 999, 'side': 'SELL'}]
    ok, reason = w._risk_ok()
    assert ok is True
    assert reason == 'ok'


def test_no_sell_without_inventory(qapp):
    w = _ready_window()
    w._cycle.buy_filled_qty = Decimal('0')
    w._cycle.sell_filled_qty = Decimal('0')
    w._run_live_cycle()
    assert w.cs_top_ask_status.text() == 'DISABLED_NO_INV'
    assert all(side != 'SELL' for side, _, _ in w.orders.placed)


def test_partial_buy_creates_immediate_sell(qapp):
    w = _ready_window()
    w._cycle.buy_filled_qty = Decimal('20')
    w._cycle.sell_filled_qty = Decimal('0')
    w._cycle.buy_avg_price = Decimal('1.1000')
    w._run_live_cycle()
    assert any(side == 'SELL' for side, _, _ in w.orders.placed)


def test_fresh_buy_not_reconciled_during_grace_window(qapp):
    w = _ready_window()
    w.orders = _AlwaysMissingOrders()
    w._run_live_cycle()
    placed_buy_id = w._cycle.buy_order_id
    assert placed_buy_id is not None
    w._last_open_orders = []
    w._run_live_cycle()
    assert w._cycle.buy_order_id == placed_buy_id


def test_fresh_sell_not_reconciled_during_grace_window(qapp):
    w = _ready_window()
    w.orders = _AlwaysMissingOrders()
    w._cycle.buy_filled_qty = Decimal('20')
    w._cycle.sell_filled_qty = Decimal('0')
    w._cycle.buy_avg_price = Decimal('1.1000')
    w._run_live_cycle()
    placed_sell_id = w._cycle.sell_order_id
    assert placed_sell_id is not None
    w._last_open_orders = []
    w._run_live_cycle()
    assert w._cycle.sell_order_id == placed_sell_id


def test_open_orders_presence_blocks_reconcile(qapp):
    w = _ready_window()
    w.orders = _AlwaysMissingOrders()
    w._cycle.buy_order_id = 42
    w._last_open_orders = [{'orderId': 42, 'side': 'BUY', 'status': 'NEW'}]
    w._run_live_cycle()
    assert w._cycle.buy_order_id == 42


def test_no_duplicate_buy_during_grace_window(qapp):
    w = _ready_window()
    w.orders = _AlwaysMissingOrders()
    w._run_live_cycle()
    assert len([x for x in w.orders.placed if x[0] == 'BUY']) == 1
    w._last_open_orders = []
    w._run_live_cycle()
    assert len([x for x in w.orders.placed if x[0] == 'BUY']) == 1
