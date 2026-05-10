from decimal import Decimal
import pytest

QtWidgets = pytest.importorskip('PySide6.QtWidgets', reason='PySide6 GUI deps are unavailable in this environment')
QApplication = QtWidgets.QApplication

from app.gui.main_window import MainWindow
from app.core.spread_stability_engine import ReadinessState


class _Orders:
    def __init__(self):
        self.placed = []
        self.cancelled = []

    def order_status(self, order_id):
        return {'status': 'NEW', 'executedQty': '0', 'price': '1.1000'}

    def place_limit_maker(self, side, qty, price):
        oid = len(self.placed) + 1
        self.placed.append((side, Decimal(str(qty)), Decimal(str(price)), oid))
        return {'orderId': oid}

    def cancel(self, order_id):
        self.cancelled.append(int(order_id))
        return {'status': 'CANCELED'}


@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])


def _w(symbol='BTCU'):
    w = MainWindow()
    w.cfg['symbol'] = symbol
    w.cfg['dynamic_aggression'] = True
    w._live_running = True
    w._private_ok = True
    w._balances = {'U_free': '10000', 'BTC_free': '0', 'QUOTE_free': '10000', 'BASE_free': '0', 'BASE_locked': '0'}
    w._last_market_snapshot = {'bid': '100.00', 'ask': '100.10'}
    w._spread_metrics = type('M', (), {'state': type('S', (), {'readiness': ReadinessState.NOT_READY})()})()
    w._fill_observation = type('F', (), {'fill_possible': False})()
    w._exchange_filters = {'tickSize': '0.01', 'stepSize': '0.001', 'minQty': '0.001', 'minNotional': '5'}
    w._require_exchange_filters = lambda: True
    w.refresh_orders = lambda force=False: None
    w.orders = _Orders()
    return w


def test_buy_chaser_cancels_far_buy_even_when_spread_not_ready(qapp):
    w = _w()
    w.cfg['buy_stale_reprice_ticks'] = 25
    w._cycle.buy_order_id = 7
    w._last_open_orders = [{'orderId': 7, 'side': 'BUY', 'price': '99.00', 'origQty': '1', 'executedQty': '0', 'status': 'NEW'}]
    w._orders_by_id = {7: w._last_open_orders[0]}
    w._run_live_cycle()
    assert w.orders.cancelled == [7]


def test_buy_chaser_cancels_far_buy_even_when_live_or_optimistic(qapp):
    w = _w()
    w.cfg['buy_stale_reprice_ticks'] = 25
    w._cycle.buy_order_id = 8
    w._optimistic_orders[99] = {'side': 'BUY'}
    w._optimistic_order_mono[99] = 0.0
    w._last_open_orders = [{'orderId': 8, 'side': 'BUY', 'price': '99.00', 'origQty': '1', 'executedQty': '0', 'status': 'NEW'}]
    w._orders_by_id = {8: w._last_open_orders[0]}
    w._run_live_cycle()
    assert w.orders.cancelled == [8]


def test_buy_working_without_position_not_position_open(qapp):
    w = _w()
    w._cycle.open_position_qty = Decimal('0')
    w._cycle.buy_order_id = 9
    w._last_open_orders = [{'orderId': 9, 'side': 'BUY', 'price': '100.00', 'origQty': '1', 'executedQty': '0', 'status': 'NEW'}]
    w._orders_by_id = {9: w._last_open_orders[0]}
    w._run_live_cycle()
    assert 9 not in w.orders.cancelled


def test_repost_next_tick_after_stale_buy_cancel(qapp):
    w = _w()
    w._cycle.buy_order_id = 10
    w._last_open_orders = [{'orderId': 10, 'side': 'BUY', 'price': '99.00', 'origQty': '1', 'executedQty': '0', 'status': 'NEW'}]
    w._orders_by_id = {10: w._last_open_orders[0]}
    w._run_live_cycle()
    assert not w.orders.placed
    w._last_open_orders = []
    w._run_live_cycle()
    assert any(side == 'BUY' for side, *_ in w.orders.placed)


def test_btcu_dynamic_aggression_buy_levels(qapp):
    w = _w()
    assert w._effective_aggr_ticks('BUY', Decimal('250')) == 0
    assert w._effective_aggr_ticks('BUY', Decimal('350')) == 80
    assert w._effective_aggr_ticks('BUY', Decimal('700')) == 150
    assert w._effective_aggr_ticks('BUY', Decimal('1500')) == 300


def test_btcu_dynamic_aggression_sell_levels(qapp):
    w = _w()
    assert w._effective_aggr_ticks('SELL', Decimal('250')) == 0
    assert w._effective_aggr_ticks('SELL', Decimal('350')) == 100
    assert w._effective_aggr_ticks('SELL', Decimal('700')) == 200
    assert w._effective_aggr_ticks('SELL', Decimal('1500')) == 400


def test_limit_maker_buy_never_crosses_ask(qapp):
    w = _w()
    price = w._safe_maker_buy_price(Decimal('100.00'), Decimal('100.01'), Decimal('0.01'))
    assert price < Decimal('100.01')
