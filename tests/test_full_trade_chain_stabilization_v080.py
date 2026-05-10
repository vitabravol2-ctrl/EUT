import time
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
        self._status = {}

    def set_status(self, order_id, payload):
        self._status[int(order_id)] = payload

    def order_status(self, order_id):
        return self._status.get(int(order_id), {'status': 'NEW', 'executedQty': '0', 'price': '1.1000'})

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


def _w():
    w = MainWindow()
    w._live_running = True
    w._private_ok = True
    w._balances = {'USDT_free': '1000', 'EURI_free': '0'}
    w._last_market_snapshot = {'bid': '1.1000', 'ask': '1.1002'}
    w._spread_metrics = type('M', (), {'state': type('S', (), {'readiness': ReadinessState.READY})()})()
    w._fill_observation = type('F', (), {'fill_possible': True})()
    w._exchange_filters = {'tickSize': '0.0001', 'stepSize': '0.01', 'minQty': '0.01', 'minNotional': '5'}
    w._require_exchange_filters = lambda: True
    w.refresh_orders = lambda force=False: None
    w.orders = _Orders()
    return w


def test_no_sell_without_position(qapp):
    w = _w()
    w._cycle.open_position_qty = Decimal('0')
    w._run_live_cycle()
    assert all(side != 'SELL' for side, *_ in w.orders.placed)


def test_no_buy_while_position_open(qapp):
    w = _w()
    w._cycle.open_position_qty = Decimal('2')
    w._cycle.buy_filled_qty = Decimal('2')
    w._run_live_cycle()
    assert all(side != 'BUY' for side, *_ in w.orders.placed)


def test_sell_qty_equals_open_position(qapp):
    w = _w()
    w._cycle.open_position_qty = Decimal('2.137')
    w._cycle.buy_filled_qty = Decimal('2.137')
    w._cycle.buy_avg_price = Decimal('1.1000')
    w._run_live_cycle()
    sell = next((o for o in w.orders.placed if o[0] == 'SELL'), None)
    assert sell is not None
    assert sell[1] == Decimal('2.13')


def test_stale_buy_reposts(qapp):
    w = _w()
    w.cfg['buy_max_age_ms'] = 1
    w._run_live_cycle()
    buy_id = w._cycle.buy_order_id
    w._last_open_orders = [{'orderId': buy_id, 'side': 'BUY', 'price': '1.0990', 'origQty': '1.0', 'executedQty': '0', 'status': 'NEW'}]
    w._orders_by_id = {buy_id: w._last_open_orders[0]}
    w._quote_birth[buy_id] = time.time() - 2
    w._quote_birth_mono[buy_id] = time.monotonic() - 2
    w._run_live_cycle()
    assert buy_id in w.orders.cancelled


def test_stale_sell_reposts(qapp):
    w = _w()
    w.cfg['sell_max_age_ms'] = 1
    w._cycle.open_position_qty = Decimal('1')
    w._cycle.buy_filled_qty = Decimal('1')
    w._cycle.buy_avg_price = Decimal('1.1000')
    w._run_live_cycle()
    sell_id = w._cycle.sell_order_id
    w._last_open_orders = [{'orderId': sell_id, 'side': 'SELL', 'price': '1.1200', 'origQty': '1', 'executedQty': '0', 'status': 'NEW'}]
    w._orders_by_id = {sell_id: w._last_open_orders[0]}
    w._quote_birth[sell_id] = time.time() - 2
    w._quote_birth_mono[sell_id] = time.monotonic() - 2
    w._run_live_cycle()
    assert sell_id in w.orders.cancelled


def test_ghost_buy_cleared(qapp):
    w = _w()
    w._cycle.buy_order_id = 77
    w._last_open_orders = []
    w.orders.set_status(77, {'status': 'CANCELED'})
    w._run_live_cycle()
    assert w._cycle.buy_order_id is None


def test_ghost_sell_cleared(qapp):
    w = _w()
    w._cycle.open_position_qty = Decimal('0')
    w._cycle.sell_order_id = 88
    w._last_open_orders = []
    w.orders.set_status(88, {'status': 'CANCELED'})
    w._run_live_cycle()
    assert w._cycle.sell_order_id is None
