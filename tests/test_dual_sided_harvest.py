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
    w._exchange_filters = {'tickSize': '0.0001', 'stepSize': '0.01', 'minQty': '0.01', 'minNotional': '5'}
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


def test_partial_sell_creates_immediate_buy(qapp):
    w = _ready_window()
    w._cycle.sell_filled_qty = Decimal('10')
    w._balances['USDT_free'] = '1000'
    w._run_live_cycle()
    assert any(side == 'BUY' for side, _, _ in w.orders.placed)


def test_position_does_not_block_runtime(qapp):
    w = _ready_window()
    w._cycle.open_position_qty = Decimal('10')
    ok, reason = w._risk_ok()
    assert ok is True
    assert reason == 'ok'


def test_gui_orders_match_exchange_orders(qapp):
    w = _ready_window()
    payload = [{'orderId': 1, 'side': 'BUY', 'price': '1.1', 'origQty': '1', 'executedQty': '0', 'status': 'NEW'}]
    w._sync_open_orders(payload)
    assert w.table.rowCount() == 1


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


def test_free_euri_enables_sell_engine(qapp):
    w = _ready_window()
    w._balances['EURI_free'] = '25'
    w._run_live_cycle()
    assert any(side == 'SELL' for side, _, _ in w.orders.placed)


def test_exchange_balances_override_local_inventory_for_sell(qapp):
    w = _ready_window()
    w._cycle.buy_filled_qty = Decimal('0')
    w._cycle.sell_filled_qty = Decimal('0')
    w._balances['EURI_free'] = '10'
    w._run_live_cycle()
    assert any(side == 'SELL' for side, _, _ in w.orders.placed)


def test_disabled_no_inv_not_triggered_with_free_euri(qapp):
    w = _ready_window()
    w._balances['EURI_free'] = '1'
    w._run_live_cycle()
    assert w.cs_top_ask_status.text() != 'DISABLED_NO_INV'


def test_continuous_dual_sided_runtime_survives_100_ticks(qapp):
    w = _ready_window()
    w._balances['EURI_free'] = '50'
    for _ in range(120):
        w._run_live_cycle()
    assert w._live_running is True


def test_buy_and_sell_coexist_simultaneously(qapp):
    w = _ready_window()
    w._balances['EURI_free'] = '20'
    w._run_live_cycle()
    sides = {side for side, _, _ in w.orders.placed}
    assert 'BUY' in sides and 'SELL' in sides


def test_sell_resize_cancels_then_reposts(qapp):
    w = _ready_window()
    w._balances['EURI_free'] = '5'
    w._last_open_orders = [{'orderId': 99, 'side': 'SELL', 'origQty': '4.54', 'executedQty': '0', 'price': '1.1001', 'status': 'NEW'}]
    w._orders_by_id = {99: w._last_open_orders[0]}
    w._cycle.sell_order_id = 99
    cancelled = []
    w.orders.cancel = lambda order_id: cancelled.append(order_id) or {'status': 'CANCELED'}
    w._run_live_cycle()
    assert cancelled == [99]
    assert any(side == 'SELL' for side, _, _ in w.orders.placed)


def test_watch_state_does_not_block_if_spread_ticks_meet_min(qapp):
    w = _ready_window()
    w._spread_metrics = type('M', (), {'state': type('S', (), {'readiness': ReadinessState.WATCH})()})()
    ok, reason = w._risk_ok()
    assert ok is True
    assert reason == 'ok'


def test_main_window_uses_exchange_filters_not_symbol_filters():
    assert '_symbol_filters' not in MainWindow._run_live_cycle.__code__.co_names


def test_sell_compute_succeeds_with_exchange_filters(qapp):
    w = _ready_window()
    w._balances['EURI_free'] = '3'
    w._cycle.buy_filled_qty = Decimal('3')
    w._cycle.sell_filled_qty = Decimal('0')
    w._run_live_cycle()
    assert any(side == 'SELL' for side, _, _ in w.orders.placed)


def test_missing_filters_does_not_crash_runtime(qapp):
    w = _ready_window()
    w._exchange_filters = {}
    w._load_exchange_filters = lambda: False
    w._balances['EURI_free'] = '5'
    w._run_live_cycle()
    assert w._live_running is True
